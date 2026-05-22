#!/usr/bin/env python3
"""
Baizora Daily Video Generator
Generates branded 1920x1080 MP4 recap videos from data/latest.json

Usage:
    py generate_video.py --type sp500_movers
    py generate_video.py --type platform_intro --output my_intro.mp4

Video types: sp500_movers, nasdaq_movers, volume_spikes, extreme_1y, platform_intro
"""

import argparse
import json
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
    draw.text((72, 28), title, font=load_font(36, bold=True), fill=WHITE)
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


def scene_movers_table(title, rows, scan_date):
    img, draw = new_frame()
    top_bar(draw, title, scan_date)

    # columns: (header, data_key, width)
    COLS = [
        ("#",         None,              70),
        ("TICKER",    "Ticker",         130),
        ("COMPANY",   "CompanyName",    310),
        ("PRICE",     "Price",          130),
        ("1D CHG%",   "PriceChange1D",  145),
        ("VOL(M)",    "VolumeM",        140),
        ("1D VOL%",   "VolumeChange1D", 165),
        ("1Y CHG%",   "1YPriceChange",  150),
    ]

    f_hdr = load_font(17, mono=True)
    f_tkr = load_font(23, mono=True)
    f_coy = load_font(19)
    f_val = load_font(22, mono=True)

    x = 60
    for hdr, _, cw in COLS:
        draw.text((x, 110), hdr, font=f_hdr, fill=DIM)
        x += cw
    hline(draw, 143)

    for idx, row in enumerate(rows[:10]):
        y = 152 + idx * 70
        if idx % 2 == 0:
            draw.rectangle([60, y - 4, W - 60, y + 62], fill=NAVY_MID)
        x = 60
        for hdr, key, cw in COLS:
            if key is None:
                draw.text((x + 10, y + 4), str(idx + 1), font=f_hdr, fill=VERY_DIM)
            elif key == "Ticker":
                draw.text((x, y), row.get(key, ""), font=f_tkr, fill=WHITE)
            elif key == "CompanyName":
                name = row.get(key) or ""
                if len(name) > 28:
                    name = name[:25] + "..."
                draw.text((x, y + 2), name, font=f_coy, fill=MUTED)
            elif key == "Price":
                v = row.get(key)
                draw.text((x, y), f"${v:.2f}" if v else "—", font=f_val, fill=WHITE)
            elif key == "VolumeM":
                v = row.get(key)
                draw.text((x, y), f"{v:.2f}M" if v else "—", font=f_val, fill=WHITE)
            else:
                v = row.get(key)
                draw.text((x, y), pct_str(v), font=f_val, fill=pct_color(v))
            x += cw

    footer(draw)
    return img


def scene_volume_spikes(rows, scan_date):
    img, draw = new_frame()
    top_bar(draw, "Volume Spikes — Unusual Activity", scan_date)

    COLS = [
        ("#",          None,               70),
        ("TICKER",     "Ticker",          130),
        ("COMPANY",    "CompanyName",     290),
        ("PRICE",      "Price",           130),
        ("1D P CHG%",  "PriceChange1D",   148),
        ("VOL(M)",     "VolumeM",         138),
        ("1D V CHG%",  "VolumeChange1D",  165),
        ("VOL/MA21",   "VolumeVsMA21_1D", 160),
    ]

    f_hdr = load_font(17, mono=True)
    f_tkr = load_font(23, mono=True)
    f_coy = load_font(19)
    f_val = load_font(22, mono=True)

    x = 60
    for hdr, _, cw in COLS:
        draw.text((x, 110), hdr, font=f_hdr, fill=DIM)
        x += cw
    hline(draw, 143)

    for idx, row in enumerate(rows[:10]):
        y = 152 + idx * 70
        if idx % 2 == 0:
            draw.rectangle([60, y - 4, W - 60, y + 62], fill=NAVY_MID)
        x = 60
        for hdr, key, cw in COLS:
            if key is None:
                draw.text((x + 10, y + 4), str(idx + 1), font=f_hdr, fill=VERY_DIM)
            elif key == "Ticker":
                draw.text((x, y), row.get(key, ""), font=f_tkr, fill=WHITE)
            elif key == "CompanyName":
                name = row.get(key) or ""
                if len(name) > 26:
                    name = name[:23] + "..."
                draw.text((x, y + 2), name, font=f_coy, fill=MUTED)
            elif key == "Price":
                v = row.get(key)
                draw.text((x, y), f"${v:.2f}" if v else "—", font=f_val, fill=WHITE)
            elif key == "VolumeM":
                v = row.get(key)
                draw.text((x, y), f"{v:.2f}M" if v else "—", font=f_val, fill=WHITE)
            elif key == "VolumeVsMA21_1D":
                v = row.get(key)
                c = GOLD if (v and v >= 3) else (GREEN if (v and v >= 1.5) else WHITE)
                draw.text((x, y), f"{v:.2f}x" if v else "—", font=f_val, fill=c)
            elif key == "VolumeChange1D":
                v = row.get(key)
                c = GOLD if (v and v > 200) else pct_color(v)
                draw.text((x, y), pct_str(v), font=f_val, fill=c)
            else:
                v = row.get(key)
                draw.text((x, y), pct_str(v), font=f_val, fill=pct_color(v))
            x += cw

    footer(draw)
    return img


def scene_volume_spikes_cn(rows, scan_date):
    img, draw = new_frame()

    # CN top bar
    draw.rectangle([0, 0, W, 96], fill=NAVY_MID)
    hline(draw, 96, x0=0, x1=W)
    draw.text((72, 22), "成交量异动 — 异常交易活动", font=load_font_cn(28, bold=True), fill=WHITE)
    f_d = load_font(20, mono=True)
    dw  = tw(draw, scan_date, f_d)
    draw.text((W - 72 - dw, 38), scan_date, font=f_d, fill=MUTED)

    COLS = [
        ("#",       None,               70),
        ("代码",    "Ticker",          130),
        ("公司",    "CompanyName",     280),
        ("价格",    "Price",           130),
        ("日价涨",  "PriceChange1D",   148),
        ("成交量M", "VolumeM",         148),
        ("日量涨",  "VolumeChange1D",  165),
        ("量/MA21", "VolumeVsMA21_1D", 160),
    ]

    f_hdr = load_font_cn(16)
    f_tkr = load_font(23, mono=True)
    f_coy = load_font_cn(17)
    f_val = load_font(22, mono=True)

    x = 60
    for hdr, _, cw in COLS:
        draw.text((x, 108), hdr, font=f_hdr, fill=DIM)
        x += cw
    hline(draw, 141)

    for idx, row in enumerate(rows[:10]):
        y = 150 + idx * 70
        if idx % 2 == 0:
            draw.rectangle([60, y - 4, W - 60, y + 62], fill=NAVY_MID)
        x = 60
        for hdr, key, cw in COLS:
            if key is None:
                draw.text((x + 10, y + 4), str(idx + 1), font=f_hdr, fill=VERY_DIM)
            elif key == "Ticker":
                draw.text((x, y), row.get(key, ""), font=f_tkr, fill=WHITE)
            elif key == "CompanyName":
                name = row.get(key) or ""
                if len(name) > 24:
                    name = name[:21] + "..."
                draw.text((x, y + 2), name, font=f_coy, fill=MUTED)
            elif key == "Price":
                v = row.get(key)
                draw.text((x, y), f"${v:.2f}" if v else "—", font=f_val, fill=WHITE)
            elif key == "VolumeM":
                v = row.get(key)
                draw.text((x, y), f"{v:.2f}M" if v else "—", font=f_val, fill=WHITE)
            elif key == "VolumeVsMA21_1D":
                v = row.get(key)
                c = GOLD if (v and v >= 3) else (GREEN if (v and v >= 1.5) else WHITE)
                draw.text((x, y), f"{v:.2f}x" if v else "—", font=f_val, fill=c)
            elif key == "VolumeChange1D":
                v = row.get(key)
                c = GOLD if (v and v > 200) else pct_color(v)
                draw.text((x, y), pct_str(v), font=f_val, fill=c)
            else:
                v = row.get(key)
                draw.text((x, y), pct_str(v), font=f_val, fill=pct_color(v))
            x += cw

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
    draw.text((_LP_X, 70), "◈   WHY BAIZORA", font=load_font(16, mono=True), fill=accent)
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
              font=load_font_cn(16), fill=accent)
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


_SS_EN = "C:/Users/hongz/Desktop/baizora_homepage_Screenshot.png"
_SS_CN = "C:/Users/hongz/Desktop/baizora_homepage_Screenshot_cn.png"


# ── Sparklines scene ─────────────────────────────────────────────────────────

def scene_sparklines(title, rows, scan_date):
    """5×2 grid: ticker info on the left, 1-year sparkline on the right."""
    img, draw = new_frame()
    top_bar(draw, title, scan_date)

    NCOLS, NROWS = 2, 5
    mgx  = 14          # horizontal margin / gap
    mgy  = 6           # vertical gap between rows
    content_top = 102
    content_bot = H - 65
    cw   = (W - 3 * mgx) // NCOLS        # cell width  ≈ 943 px
    ch   = (content_bot - content_top - (NROWS - 1) * mgy) // NROWS   # ≈ 174 px
    info_w = 220       # left info column width

    f_tkr = load_font(22, mono=True)
    f_co  = load_font(16)
    f_val = load_font(17, mono=True)

    spark_polys = []   # filled areas, composited via RGBA at the end

    for idx, row in enumerate(rows[:10]):
        ci = idx % NCOLS
        ri = idx // NCOLS
        x0 = mgx + ci * (cw + mgx)
        y0 = content_top + ri * (ch + mgy)
        x1 = x0 + cw
        y1 = y0 + ch

        draw.rectangle([x0, y0, x1, y1], fill=NAVY_MID)

        # ── Info section ──────────────────────────────────────────────────
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

        # Divider
        draw.line([(x0 + info_w, y0 + 8), (x0 + info_w, y1 - 8)],
                  fill=BORDER, width=1)

        # ── Sparkline ─────────────────────────────────────────────────────
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

                # Fill polygon (composited later)
                spark_polys.append(
                    pts + [(pts[-1][0], sy0 + sh), (pts[0][0], sy0 + sh)]
                )

                # Line
                line_c = GREEN if (pc1y or 0) >= 0 else RED
                for j in range(len(pts) - 1):
                    draw.line([pts[j], pts[j+1]], fill=line_c, width=2)

                # Today dot
                draw.ellipse([pts[-1][0]-4, pts[-1][1]-4,
                               pts[-1][0]+4, pts[-1][1]+4], fill=ELEC_BRIGHT)

    # Composite sparkline fills
    if spark_polys:
        ov  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ovd = ImageDraw.Draw(ov)
        for poly in spark_polys:
            ovd.polygon(poly, fill=(59, 130, 246, 28))
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
                f"{parts[0]}, {parts[1]}, and {parts[2]}.")
    elif parts:
        return "Today's top volume spikes: " + " and ".join(parts) + "."
    return ""


def _narrate_volume_cn(rows):
    top = rows[:3]
    parts = []
    for r in top:
        ticker = r.get("Ticker", "")
        v      = r.get("VolumeChange1D") or 0
        parts.append(f"{ticker}成交量上涨{abs(v):.0f}%")
    if len(parts) >= 3:
        return f"今日成交量异动前三名：{parts[0]}，{parts[1]}，以及{parts[2]}。"
    elif parts:
        return "今日成交量异动：" + "，".join(parts) + "。"
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
        for pref_start, clip in clips:
            if clip is None:
                continue
            actual_start   = max(pref_start, earliest_next)
            clip_dur       = len(clip) / sr
            earliest_next  = actual_start + clip_dur + GAP
            s = int(actual_start * sr); e = min(s + len(clip), n)
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


def encode(frames, output, xfade_frames=30, tts_voice="en-US-ChristopherNeural"):
    """
    frames: list of (Image, hold_sec [, subtitle [, narration]])
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
            for _ in range(int(hold_sec * FPS)):
                save(img, subtitle)
            if i < len(frames) - 1:
                next_img = frames[i + 1][0]
                next_sub = frames[i + 1][2] if len(frames[i + 1]) > 2 else None
                for t in range(xfade_frames):
                    blend = Image.blend(img, next_img, t / xfade_frames)
                    save(blend, subtitle if t < xfade_frames // 2 else next_sub)

        print(f"  Rendering {idx} frames ({total_sec:.1f}s)...")

        music_wav = str(Path(tmp) / "music.wav")
        narr_wav  = str(Path(tmp) / "narration.wav")

        print("  Generating background music...")
        generate_music(total_sec + 0.5, music_wav)

        print("  Generating narration (TTS)...")
        generate_narration(scene_scripts, total_sec + 0.5, narr_wav, ffmpeg,
                           voice=tts_voice)

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


def build_volume_spikes(data, output):
    date   = data["date"]
    spikes = sorted(data["data"],
                    key=lambda r: r.get("VolumeChange1D") or -9999, reverse=True)[:10]

    encode([
        (scene_title("Volume Spikes", "S&P 500  ·  Nasdaq-100", date,
                     "Unusual Activity — Highest 1-Day Volume Surge vs 21-Day Average"), 4,
         "Unusual volume can signal institutional activity, earnings reactions, or breaking news",
         f"Volume spike report for S&P 500 and Nasdaq-100 stocks, {date}, from Baizora."),
        (scene_volume_spikes(spikes, date), 14,
         "VOL/MA21 = today's volume vs 21-day average  |  values above 3x highlighted in gold",
         f"{_narrate_volume(spikes)} "
         "Want to know more about short and mid term price and volume data "
         "for S&P 500 and Nasdaq-100 stocks? "
         "Visit baizora dot com."),
        (scene_screenshot(_SS_EN), 2),
        (scene_outro(date), 5,
         "For informational purposes only. Not financial advice. | baizora.com"),
    ], output)


def build_extreme_1y(data, output):
    date    = data["date"]
    gainers = sorted(data["data"],
                     key=lambda r: r.get("1YPriceChange") or -9999, reverse=True)[:10]

    def _fmt_gain(v):
        v = abs(v)
        if v >= 200:
            return f"{round(v / 100):.0f} times"
        return f"{v:.0f} percent"

    def _narrate_1y(rows):
        top = rows[:5]
        parts = []
        for r in top:
            ticker = r.get("Ticker", "")
            v      = r.get("1YPriceChange") or 0
            parts.append(f"{ticker} up {_fmt_gain(v)}")
        if len(parts) >= 2:
            return ("Top twelve-month performers: "
                    + ", ".join(parts[:-1]) + f", and {parts[-1]}.")
        elif parts:
            return f"Top twelve-month performer: {parts[0]}."
        return ""

    encode([
        (scene_title("1-Year Best Performers", "S&P 500  ·  Nasdaq-100", date,
                     "Large-Cap Leaders — Trailing 12 Months"), 4,
         "Best large-cap stocks over the past 12 months — S&P 500 + Nasdaq-100",
         f"One-year performance leaders among S&P 500 and Nasdaq-100 stocks, as of {date}, from Baizora."),
        (scene_movers_table(f"Top 10 Gainers — 1 Year  ({date})", gainers, date), 12,
         "S&P 500 + Nasdaq-100 stocks — highest trailing 12-month price appreciation",
         f"{_narrate_1y(gainers)}"),
        (scene_sparklines(f"1-Year Leaders — Price Trend  ({date})", gainers, date), 12,
         "1-year price trend for each top performer — bright dot marks today",
         "Here are the one-year price charts for the top performers "
         "across S&P 500 and Nasdaq-100 stocks. "
         "Each line covers the full trailing year of price action. "
         "Bright dot marks today's price. "
         "Want to know more about short and mid term price and volume data? "
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


def build_volume_spikes_cn(data, output):
    date   = data["date"]
    spikes = sorted(data["data"],
                    key=lambda r: r.get("VolumeChange1D") or -9999, reverse=True)[:10]

    encode([
        (scene_title_cn("今日成交量异动", "S&P 500  ·  纳斯达克100", date,
                        "大盘股异常交易活动 — 贝佐拉"), 6,
         "S&P 500 + 纳斯达克100 大盘股异常交易活动 — 贝佐拉",
         "贝佐拉追踪S&P 500和纳斯达克100全部大盘股的每日成交量异动。"),
        (scene_volume_spikes_cn(spikes, date), 14,
         "量/MA21 = 今日成交量 / 21日均量  |  超过3倍的用金色高亮显示",
         f"{_narrate_volume_cn(spikes)}"
         "量除以MA21超过三倍的用金色高亮显示，代表异常活跃的交易活动。"
         "想了解更多S&P 500和纳斯达克100的价量分析数据？访问贝佐拉点com。"),
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
            narr = narr + "想了解更多关于短中期价格和成交量的分析数据？访问贝佐拉点com。"
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
    "extreme_1y":         build_extreme_1y,
    "platform_intro":     build_platform_intro,
    "platform_intro_cn":  build_platform_intro_cn,
    "volume_spikes_cn":   build_volume_spikes_cn,
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
