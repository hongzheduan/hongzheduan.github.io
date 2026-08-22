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
    py generate_shorts.py --type near_sma200
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
    FREE_ACCESS_MODE,
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
    # Real art added 2026-08-22 (video/covering/SMA200_1-4.png, split from
    # video/covering/sma200.png) -- replaces Monday's retired volume_spikes
    # category (see build_near_sma200_short). Old Monday_1-4.png (volume_spikes'
    # art) left in place, unreferenced -- not deleted, just orphaned.
    "near_sma200": "SMA200",
    "best_performer": "Tuesday",
    "6m_breakout": "Wednesday",
    "1y_vol_peak": "Thursday",
    "index_spotlight": "Friday",
    # Real Saturday art added 2026-08-01 (video/covering/Saturday_1-4.png, split
    # from video/covering/saturday.png). Sunday still has no dedicated art --
    # deliberately kept on Thursday's set (user's explicit call, not a gap).
    "worst_performer": "Saturday",
    "avg_volume": "Thursday",
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


def new_frame_s(bg=NAVY):
    img = Image.new("RGB", (SW, SH), bg)
    return img, ImageDraw.Draw(img)


def centered_s(draw, y, text, font, fill=WHITE):
    w = tw(draw, text, font)
    draw.text(((SW - w) // 2, y), text, font=font, fill=fill)


def hline_s(draw, y, x0=50, x1=None, color=BORDER, width=2):
    draw.line([(x0, y), (x1 if x1 else SW - 50, y)], fill=color, width=width)


def _wrap_text(draw, text, font, max_width, lang):
    """Greedy word-wrap for EN (space-separated) / char-wrap for CN (no spaces
    between words, so wrapping has to measure character-by-character instead)."""
    units = list(text) if lang == "cn" else text.split(" ")
    sep = "" if lang == "cn" else " "
    lines, cur = [], ""
    for u in units:
        trial = cur + (sep if cur else "") + u
        if not cur or tw(draw, trial, font) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = u
    if cur:
        lines.append(cur)
    return lines


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


# ── Light theme (share cards only) ──────────────────────────────────────────────
# The video and dashboard keep the dark-navy brand look everywhere; this palette
# exists only for the standalone downloadable share images, which get their own
# fully separate render (not a recolor of the dark video frame — swapping a navy
# background for white needs real re-rendering, since text/candle/grid colors
# tuned for contrast against navy don't automatically read on white).
_LT_BG        = (248, 250, 252)   # slate-50
_LT_GRID_DOT  = (226, 232, 240)   # slate-200
_LT_GRID_LINE = (226, 232, 240)
_LT_BORDER    = (203, 213, 225)   # slate-300
_LT_TEXT_PRI  = (15, 23, 42)      # slate-900 — ticker, badge text
_LT_TEXT_SEC  = (71, 85, 105)     # slate-600 — company name, captions
_LT_TEXT_DIM  = (100, 116, 139)   # slate-500 — lighter than DIM (148,163,184) reads
                                   # fine on navy but is too pale for good contrast on white
_LT_GOLD      = (180, 83, 9)      # amber-700 — GOLD/GOLD_LIGHT are tuned bright/pale for
                                   # pop against navy; both read as low-contrast yellow on
                                   # white, so headline/eyebrow text on the light card uses
                                   # this darker amber instead. Gold-on-navy chips (join/peak
                                   # markers) keep GOLD unchanged — their background is navy
                                   # on both themes, so contrast is already fine there.
_LT_AXIS_BG   = _LT_BG
_LT_VOL_GREEN = (187, 247, 208)   # green-200 — a straight alpha-blend of GREEN over
_LT_VOL_RED   = (254, 202, 202)   # red-200 — white washes out far more than over navy


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


def _compute_range_extremes(ticker):
    """Highest/lowest close over the full displayed 1Y candles.json window (the
    same `bars` _draw_candles_with_volume plots), and the % each represents
    relative to the window's first close (period start) -- used by every ranking
    category's per-ticker card (user request, 2026-08-01) to mark the price swing
    on the chart and narrate it, in addition to whatever category-specific metric
    that card already shows. Close-based (not high/low), matching the existing
    peak_idx convention elsewhere in this file ("close on the peak day, matches
    _compute_breakouts").

    No magnitude filtering -- initially suspected SNDK's +5340%/MU's +1013%
    peaks (2026-08-01 session) were bad/unadjusted-split data and added a
    sanity cap, but the user confirmed both are real (SNDK genuinely rose
    30-50x that year). Reverted -- plain min/max, no guard. If a future ticker
    genuinely does show implausible bad data, investigate that specific ticker
    rather than reintroducing a blanket cap that would suppress real outliers
    like SNDK."""
    bars = _load_candles().get("data", {}).get(ticker) or []
    n = len(bars)
    if n < 2:
        return None
    closes = [b[3] for b in bars]
    ref_price = closes[0]
    if ref_price <= 0:
        return None
    hi_idx = max(range(n), key=lambda i: closes[i])
    lo_idx = min(range(n), key=lambda i: closes[i])
    return {
        "hi_idx": hi_idx, "lo_idx": lo_idx,
        "hi_pct": (closes[hi_idx] - ref_price) / ref_price * 100,
        "lo_pct": (closes[lo_idx] - ref_price) / ref_price * 100,
    }


def _range_narration_line(range_ext, lang):
    if not range_ext:
        return None
    lo_str, hi_str = pct_str(range_ext["lo_pct"]), pct_str(range_ext["hi_pct"])
    if lang == "cn":
        return f"过去一年，涨跌区间为{lo_str}至{hi_str}。"
    return f"Over the past year, it ranged from {lo_str} to {hi_str}."


# Real edge-tts measurement at SHORTS_TTS_RATE, worst-case magnitude ("-95%"/"+342%"):
# EN 4.70s, CN 4.22s, +buffer.
_RANGE_DUR_EN = 5.5
_RANGE_DUR_CN = 5.0


_SMA200_LINE_COLOR = (167, 139, 250)  # matches the dashboard's own SMA200 overlay
# color (violet-400 #a78bfa), sampled directly from a real chart screenshot
# (video/sma200_sample.png) rather than picked freehand, so the video's line
# reads as "the same feature" to anyone who's seen it on the site.


def _draw_candles_with_volume(img, draw, ticker, region, peak_idx=None, peak_label=None, lang="en", theme="dark", range_ext=None, show_sma200=False):
    """Real 1-year daily OHLCV candlesticks + a volume panel underneath (price ~78%
    / volume ~22%, volume bars color-matched to candle direction at reduced opacity)
    — same visual language as the real dashboard's candlestick chart, replacing the
    close-only sparkline so the card shows actual price action, not a smoothed line.

    peak_idx (optional): index into `bars` for the previous-high day (matches
    row["_peak_idx"] from _compute_breakouts, which indexes the same tail(252)
    window as candles.json — see generate_video.py's export_candles). When given,
    draws the same gold dashed-line + dot "previous high" marker the landscape
    video's scene_breakout_sparklines has always had, brought back for Shorts.

    theme="light" (share cards only): swaps candle/gridline/axis colors for the
    light palette — GREEN/RED (not the neon BRIGHT_GREEN/BRIGHT_RED tuned for
    navy) read as washed-out on white, and the axis backing chip needs to match
    the light background instead of navy. The gold peak marker (line/dot/pill,
    which is already a dark NAVY chip with GOLD text/outline) is left unchanged —
    a dark accent chip reads fine as a highlight on a light card too."""
    is_light = theme == "light"
    candle_green = GREEN if is_light else BRIGHT_GREEN
    candle_red = RED if is_light else BRIGHT_RED
    vol_green = _LT_VOL_GREEN if is_light else _VOL_GREEN
    vol_red = _LT_VOL_RED if is_light else _VOL_RED
    grid_color = _LT_GRID_LINE if is_light else (28, 42, 68)
    axis_bg = _LT_AXIS_BG if is_light else (6, 13, 31)
    axis_text = _LT_TEXT_DIM if is_light else DIM

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
    sma200_vals = None
    if show_sma200:
        # Same candles.json "sma" dict the TECH tab's computeSmaDist reads
        # (see project_tech_view_sma_distance memory) -- index-aligned with
        # `bars`, so no date-matching needed. Extend the price axis's own
        # min/max to include the SMA200 series too, so the line is never
        # clipped even on a card where price and the average sit close
        # together (the whole point of this category).
        sma200_vals = (_load_candles().get("sma", {}).get(ticker, {}).get("sma200") or [])[:len(bars)]
        valid = [v for v in sma200_vals if v is not None]
        if valid:
            mn_v = min(mn_v, min(valid))
            mx_v = max(mx_v, max(valid))
        else:
            sma200_vals = None
    if mx_v <= mn_v:
        return
    max_vol = max(vols) or 1

    n = len(bars)
    slot_w = (x1 - x0) / n
    body_w = max(1.0, slot_w * 0.6)

    def py(v):
        return price_y1 - (v - mn_v) / (mx_v - mn_v) * (price_y1 - price_y0)

    # Faint reference gridlines at 3 price levels, drawn under the candles (not on
    # top) so they read as scale, not clutter — labels for these are drawn last,
    # after the peak marker, so they always stay legible on top of everything else.
    grid_levels = [mn_v, (mn_v + mx_v) / 2, mx_v]
    for lvl in grid_levels:
        gy = py(lvl)
        draw.line([(x0, gy), (x1, gy)], fill=grid_color, width=1)

    # SMA200 overlay, drawn before the candles so the candle bodies sit visibly
    # on top of it where price crosses the average -- that crossing/hugging is
    # the entire visual point for Monday's near_sma200 category.
    if sma200_vals:
        pts = [(x0 + (i + 0.5) * slot_w, py(v)) for i, v in enumerate(sma200_vals) if v is not None]
        if len(pts) >= 2:
            draw.line(pts, fill=_SMA200_LINE_COLOR, width=3, joint="curve")

    for i, (o, h, l, c, v) in enumerate(bars):
        cx = x0 + (i + 0.5) * slot_w
        up = c >= o
        color = candle_green if up else candle_red
        draw.line([(cx, py(h)), (cx, py(l))], fill=color, width=1)
        top, bot = py(max(o, c)), py(min(o, c))
        if bot - top < 1:
            bot = top + 1
        draw.rectangle([cx - body_w / 2, top, cx + body_w / 2, bot], fill=color)

        vh = (v / max_vol) * (vol_y1 - vol_y0)
        vol_color = vol_green if up else vol_red
        draw.rectangle([cx - body_w / 2, vol_y1 - vh, cx + body_w / 2, vol_y1], fill=vol_color)

    # "1Y TREND" label — same wording as the real dashboard's column header (see
    # CLAUDE.md) — so the chart states its own timeframe instead of leaving a
    # reader to guess how far back 252 daily candles actually go.
    tf_label = "1Y TREND" if lang == "en" else "年趋势线"
    f_tf = load_font(15, mono=True, bold=True) if lang == "en" else load_font_cn(15, bold=True)
    draw.text((x0, price_y0 - 22), tf_label, font=f_tf, fill=axis_text)
    if sma200_vals:
        # Placed right after "1Y TREND" on the same line, not right-aligned to
        # x1 -- that side is the price axis's own territory (dollar chips at 3
        # gridline heights, one of them sitting right at this same y for a chart
        # whose high is near the top of its range), and its chip backgrounds
        # would paint over a right-aligned label here since they're drawn after
        # this point in the function. A bare colored line with no label at all
        # would just read as an unexplained squiggle in a narration-less frame.
        tf_label_w = tw(draw, tf_label, f_tf)
        draw.text((x0 + tf_label_w + 16, price_y0 - 22), "— SMA200", font=f_tf, fill=_SMA200_LINE_COLOR)

    # Price axis: dollar value at each of the 3 gridlines, right-aligned to the
    # chart's right edge with a small backing chip so it stays readable regardless
    # of what candles/peak-marker pill are behind it at that height.
    f_axis = load_font(22, mono=True, bold=True)
    for idx, lvl in enumerate(grid_levels):
        gy = py(lvl)
        label = f"${lvl:,.0f}" if lvl >= 100 else f"${lvl:,.2f}"
        lbl_w = tw(draw, label, f_axis)
        pad = 5
        ty = gy - 13 if idx < 2 else gy - 23  # keep the top level's chip from clipping above the panel
        lx1 = x1 - 4
        draw.rectangle([lx1 - lbl_w - pad * 2, ty - pad + 1, lx1, ty + 22 + pad - 1], fill=axis_bg)
        draw.text((lx1 - lbl_w - pad, ty), label, font=f_axis, fill=axis_text)

    if peak_idx is not None and 0 <= peak_idx < n:
        pk_price = bars[peak_idx][3]  # close on the peak day, matches _compute_breakouts (Spark1Y/close-based)
        pk_x = x0 + (peak_idx + 0.5) * slot_w
        pk_y = py(pk_price)
        draw.line([(pk_x, price_y0), (pk_x, price_y1)], fill=GOLD, width=1)
        for ddx in range(0, round(x1 - x0), 8):
            lx0 = x0 + ddx
            lx1 = min(x0 + ddx + 4, x1)
            draw.line([(lx0, pk_y), (lx1, pk_y)], fill=GOLD, width=1)
        if peak_label:
            # CN peak labels (e.g. "前高") need a CJK-capable font — a plain mono
            # font here rendered CN text as tofu boxes, the same bug already fixed
            # once for scene_ad_short's CN date line (see project memory).
            # Same dark-chip-with-gold-text treatment the Friday "JOINED" marker
            # used to have — dropped for the same reason: illegible against the
            # light-card background. Plain bold electric-blue text instead, no
            # box, matching the JOINED label fix.
            f_lbl = load_font(22, mono=True, bold=True) if lang == "en" else load_font_cn(22, bold=True)
            lbl_w = tw(draw, peak_label, f_lbl)
            gap = 14  # clears the dot's r=7 radius
            # Anchored beside the dot (not the chart's far edge, which could sit far
            # from the marker it's meant to label) — flips to the dot's left when
            # there isn't enough room on the right so it never runs off-canvas.
            if x1 - pk_x - gap >= lbl_w:
                lbl_x = pk_x + gap
            else:
                lbl_x = pk_x - gap - lbl_w
            lbl_y = pk_y - 28 if pk_y - price_y0 > 30 else pk_y + 12
            lbl_color = ELECTRIC if is_light else ELEC_BRIGHT
            draw.text((lbl_x, lbl_y), peak_label, font=f_lbl, fill=lbl_color)
        draw.ellipse([pk_x - 7, pk_y - 7, pk_x + 7, pk_y + 7], fill=GOLD)

    if range_ext:
        # Highest/lowest close over the whole displayed window (user request,
        # 2026-08-01) -- same dot-plus-flip-label visual language as the peak_idx
        # marker above and Friday spotlight's PEAK/LOW dots (see
        # project-friday-spotlight-maxmin), just without a vertical dashed line
        # (peak_idx already owns that visual for Wednesday's breakout category;
        # a second full-height line here would clutter the chart).
        f_rg = load_font(20, mono=True, bold=True) if lang == "en" else load_font_cn(20, bold=True)

        def _draw_range_marker(idx, pct, is_peak):
            if not (0 <= idx < n):
                return
            rx = x0 + (idx + 0.5) * slot_w
            ry = py(bars[idx][3])
            mk_color = (GREEN if is_light else BRIGHT_GREEN) if is_peak else (RED if is_light else BRIGHT_RED)
            draw.ellipse([rx - 8, ry - 8, rx + 8, ry + 8], fill=mk_color)
            word = ("PEAK" if is_peak else "LOW") if lang == "en" else ("最高" if is_peak else "最低")
            label = f"{word} {pct_str(pct)}"
            lbl_w = tw(draw, label, f_rg)
            gap = 14
            if x1 - rx - gap >= lbl_w:
                lbl_x = rx + gap
            else:
                lbl_x = rx - gap - lbl_w
            if is_peak:
                lbl_y = ry - 30 if ry - price_y0 > 36 else ry + 12
            else:
                lbl_y = ry + 12 if price_y1 - ry > 36 else ry - 30
            draw.text((lbl_x, lbl_y), label, font=f_rg, fill=mk_color)

        _draw_range_marker(range_ext["hi_idx"], range_ext["hi_pct"], is_peak=True)
        _draw_range_marker(range_ext["lo_idx"], range_ext["lo_pct"], is_peak=False)


def scene_stock_card(row, rank, lang, value_key, sub_en, sub_cn, gold_leader=True,
                      peak_label_en=None, peak_label_cn=None, theme="dark", value_fmt="pct",
                      show_sma200=False):
    """Hero card for a single ticker — replaces the old shared 5-row table so the
    Short shows one stock at a time (name + the narrated metric + its 1-year
    candlestick trend, all together) instead of a static list everyone's narrated
    line points at identically. sub_en/sub_cn label whichever metric value_key is.

    peak_label_en/cn (optional): when the row carries a "_peak_idx" (set by
    _compute_breakouts for Wednesday's breakout category), passing a label here
    draws the gold "previous high" dot + dashed line on the candlestick chart —
    the same marker the landscape video's breakout scene has always had.

    value_fmt="pct" (default): value_key is a +/- percent, colored green/red by
    sign via pct_str(). value_fmt="volume" (Sunday's avg-volume category): the
    metric is a raw share count with no "good/bad" direction, so it's shown as
    "N.NM" instead and colored neutral electric-blue rather than green/red.

    theme="light" (share cards only): the video always renders theme="dark" —
    this is a real re-render with swapped colors throughout, not a recolor of
    an existing dark frame."""
    is_light = theme == "light"
    img, draw = new_frame_s(bg=_LT_BG if is_light else NAVY)
    dot_grid_s(draw, color=_LT_GRID_DOT if is_light else (20, 35, 65))

    ticker = row.get("Ticker", "")
    f_tkr = load_headline_font(90) if lang == "en" else load_font_cn(72, bold=True)
    centered_s(draw, 145, ticker, f_tkr, _LT_TEXT_PRI if is_light else WHITE)

    name = (row.get("CompanyName") or "")
    if len(name) > 30:
        name = name[:27] + "..."
    centered_s(draw, 270, name, load_font(32, bold=True) if lang == "en" else load_font_cn(30, bold=True), _LT_TEXT_SEC if is_light else MUTED)

    v = row.get(value_key)
    if value_fmt == "volume":
        color = ELECTRIC if is_light else ELEC_BRIGHT
    elif is_light:
        color = GREEN if (v or 0) >= 0 else RED
    else:
        color = BRIGHT_GREEN if (v or 0) >= 0 else BRIGHT_RED
    # Trend region height cut to 3/4 of the original (350 -> SH-560) span, anchored
    # at the same top so the freed space collapses upward instead of leaving the
    # chart floating in the middle of a now-oversized box.
    full_h = (SH - 560) - 350
    region = (110, 350, SW - 110, 350 + round(full_h * 0.75))
    peak_idx = row.get("_peak_idx")
    peak_label = (peak_label_en if lang == "en" else peak_label_cn) if peak_idx is not None else None
    range_ext = row.get("_range_ext")
    _draw_candles_with_volume(img, draw, ticker, region, peak_idx=peak_idx, peak_label=peak_label, lang=lang, theme=theme, range_ext=range_ext, show_sma200=show_sma200)

    f_pct = load_headline_font(130)
    pct_y = region[3] + 40
    pct_text = f"{v:,.1f}M" if value_fmt == "volume" else pct_str(v)
    centered_s(draw, pct_y, pct_text, f_pct, color)
    # Anton's glyph bbox top isn't flush with 0 (unlike most fonts) — use the actual
    # bbox bottom, not draw-y + th(), or the label below collides with the glyph tail.
    pct_bottom = pct_y + draw.textbbox((0, 0), pct_text, font=f_pct)[3]
    sub = sub_en if lang == "en" else sub_cn
    centered_s(draw, pct_bottom + 30, sub, load_font(24, mono=True) if lang == "en" else load_font_cn(22),
               _LT_TEXT_DIM if is_light else DIM)
    return img


# ── Scene 2b': Friday — 1-year trend with a join-date marker ───────────────────────

def scene_member_spotlight_short(member, scan_date, lang="en", theme="dark"):
    """Portrait version of generate_video.py's scene_spotlight_sparkline — pre-join
    segment muted gray, post-join segment colored green/red, with a gold join marker,
    so the "index inclusion changed the trajectory" story reads in one glance.

    theme="light" (share cards only) — see scene_stock_card's docstring; same
    real-re-render approach, not a recolor."""
    is_light = theme == "light"
    img, draw = new_frame_s(bg=_LT_BG if is_light else NAVY)
    dot_grid_s(draw, color=_LT_GRID_DOT if is_light else (20, 35, 65))
    row = member["row"]
    ticker = member["ticker"]
    perf = member["perf_since_join"]
    spark_idx = member["spark_idx"]
    if is_light:
        color = GREEN if perf >= 0 else RED
    else:
        color = BRIGHT_GREEN if perf >= 0 else BRIGHT_RED

    title = f"{ticker} — NEW MEMBER" if lang == "en" else f"{ticker} — 新晋成分股"
    f_title = load_headline_font(56) if lang == "en" else load_font_cn(46, bold=True)
    centered_s(draw, 100, title, f_title, _LT_GOLD if is_light else GOLD_LIGHT)

    name = (row.get("CompanyName") or "")
    idx_label = member["index_name"] if lang == "en" else ("纳斯达克100" if "Nasdaq" in member["index_name"] else "标普500")
    centered_s(draw, 210, f"{name}  ·  {idx_label}", load_font(28, bold=True) if lang == "en" else load_font_cn(26, bold=True),
               _LT_TEXT_SEC if is_light else MUTED)

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
                if is_light:
                    # _glow_line composites its blur against a black canvas — on
                    # navy that bleed is invisible, but on a light card it shows
                    # up as a dark smudge/halo around the line. The "neon glow"
                    # look is inherently a dark-theme effect anyway (glows read as
                    # light against black, not light against white), so the light
                    # theme just draws a plain thicker line instead.
                    draw.line(post_pts, fill=color, width=8, joint="curve")
                else:
                    _glow_line(img, draw, post_pts, color, width=8, glow_radius=20)
            jx, jy = pts[si]
            draw.line([(jx, y0), (jx, y1)], fill=GOLD, width=2)
            r = 14
            draw.polygon([(jx, jy - r), (jx - r, jy + r), (jx + r, jy + r)], fill=GOLD)

            # "JOINED {N} DAYS AGO" label beside the marker. Used to be a dark chip
            # with gold text (matching the breakout chart's "PREV HIGH" pill) but
            # the gold-on-navy chip was hard to read at a glance — dropped the box/
            # border entirely and switched to plain bold electric-blue text, which
            # reads clearly against both the navy and light-card backgrounds
            # without needing a background fill.
            # Shows trading days since join (bdays_since_join, already computed by
            # _get_verified_members for the spoken narration) rather than the exact
            # calendar join_date — that date comes from a manually-curated source
            # (verified_new_member.txt) that can lag the real S&P/Nasdaq effective
            # date, so stating it as a specific day overclaims precision the data
            # doesn't have. A relative "N trading days ago" reads as approximate.
            bdays = member["bdays_since_join"]
            join_label = f"JOINED {bdays}D AGO" if lang == "en" else f"{bdays}个交易日前加入"
            f_join = load_font(22, mono=True, bold=True) if lang == "en" else load_font_cn(22, bold=True)
            jlbl_w = tw(draw, join_label, f_join)
            gap = 20  # clears the triangle's r=14 half-width
            if x1 - jx - gap >= jlbl_w:
                jlbl_x = jx + gap
            else:
                jlbl_x = jx - gap - jlbl_w
            jlbl_y = y0 + 8
            join_color = ELECTRIC if is_light else ELEC_BRIGHT
            draw.text((jlbl_x, jlbl_y), join_label, font=f_join, fill=join_color)

            # Peak-gain / trough-loss markers -- the highest and lowest the stock
            # has traded since joining, not just where it stands right now. Same
            # dot-plus-flip-label visual language as the breakout chart's "PREV
            # HIGH" pill (see _draw_candles_with_volume), just without a full
            # vertical dashed line (that's reserved for the join point) and with
            # a self-explanatory "PEAK"/"LOW" word so the marker still reads
            # correctly on a share-card screenshot with no narration attached.
            max_gain = member.get("max_gain_since_join")
            max_loss = member.get("max_loss_since_join")
            max_gain_idx = member.get("max_gain_idx", si)
            max_loss_idx = member.get("max_loss_idx", si)
            f_mk = load_font(22, mono=True, bold=True) if lang == "en" else load_font_cn(22, bold=True)

            def _draw_extreme_marker(idx, value, is_peak):
                if value is None or not (0 <= idx < n):
                    return
                mkx, mky = pts[idx]
                mk_color = (GREEN if is_light else BRIGHT_GREEN) if is_peak else (RED if is_light else BRIGHT_RED)
                draw.ellipse([mkx - 9, mky - 9, mkx + 9, mky + 9], fill=mk_color)
                word = ("PEAK" if is_peak else "LOW") if lang == "en" else ("最高" if is_peak else "最低")
                label = f"{word} {pct_str(value)}"
                lbl_w = tw(draw, label, f_mk)
                gap = 16  # clears the dot's r=9 radius
                if x1 - mkx - gap >= lbl_w:
                    lbl_x = mkx + gap
                else:
                    lbl_x = mkx - gap - lbl_w
                # Peaks label above the dot, troughs below -- flips inward if that
                # would run off the chart's top/bottom edge.
                if is_peak:
                    lbl_y = mky - 34 if mky - y0 > 40 else mky + 14
                else:
                    lbl_y = mky + 14 if y1 - mky > 40 else mky - 34
                draw.text((lbl_x, lbl_y), label, font=f_mk, fill=mk_color)

            _draw_extreme_marker(max_gain_idx, max_gain, is_peak=True)
            _draw_extreme_marker(max_loss_idx, max_loss, is_peak=False)

    f_pct = load_headline_font(120)
    pct_y = SH - 440
    pct_text = pct_str(perf)
    centered_s(draw, pct_y, pct_text, f_pct, color)
    pct_bottom = pct_y + draw.textbbox((0, 0), pct_text, font=f_pct)[3]
    footer = "SINCE JOINING THE INDEX" if lang == "en" else "加入指数以来"
    centered_s(draw, pct_bottom + 30, footer, load_font(30, mono=True, bold=True) if lang == "en" else load_font_cn(28, bold=True),
               _LT_TEXT_DIM if is_light else DIM)
    return img


# ── Shareable stock-card images (social media downloads) ───────────────────────────
# Reuses the exact card already rendered for the video (scene_stock_card /
# scene_member_spotlight_short) — same row/member data, so there's no risk of the
# share image disagreeing with what the video actually shows (e.g. Friday's member
# is picked once via random.choice and the share card is stamped from that same
# object, not re-picked). This footer only adds what a standalone image needs that
# the video doesn't: a one-line explanation of what it is, the date, and a quiet
# brand mark — into the blank space every card already has below its content.

def _add_criteria_banner(card_img, criteria, lang, theme="light"):
    """Prepends a top banner explaining HOW the stock was screened (e.g. "Screened
    from S&P 500 + Nasdaq-100 for the largest volume spike vs. the 21-day average")
    — distinct from the footer's caption, which states the specific RESULT for this
    one stock (e.g. "Unusual volume spike vs the 21-day average"). Added so a share
    card is fully self-explanatory when posted to social media with no extra
    caption written by hand. Grows the canvas rather than overlaying existing
    content, since the card's own top region (rank badge at y=80) has no blank
    space to draw into without a real resize."""
    is_light = theme == "light"
    bg = _LT_BG if is_light else NAVY
    text_color = _LT_TEXT_SEC if is_light else MUTED
    eyebrow = "HOW THIS WAS SELECTED" if lang == "en" else "筛选标准"
    f_eyebrow = load_font(24, mono=True, bold=True) if lang == "en" else load_font_cn(22, bold=True)
    f_body = load_font(30, bold=True) if lang == "en" else load_font_cn(28, bold=True)

    tmp_draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    max_w = SW - 160
    lines = _wrap_text(tmp_draw, criteria, f_body, max_w, lang)

    pad_top, gap, line_gap, pad_bottom = 40, 16, 10, 32
    eyebrow_h = th(tmp_draw, eyebrow, f_eyebrow)
    line_h = th(tmp_draw, lines[0], f_body) if lines else 0
    banner_h = pad_top + eyebrow_h + gap + len(lines) * (line_h + line_gap) + pad_bottom

    new_img = Image.new("RGB", (SW, banner_h + card_img.height), bg)
    new_img.paste(card_img, (0, banner_h))
    draw = ImageDraw.Draw(new_img)

    y = pad_top
    centered_s(draw, y, eyebrow, f_eyebrow, _LT_GOLD if is_light else GOLD)
    y += eyebrow_h + gap
    for line in lines:
        centered_s(draw, y, line, f_body, text_color)
        y += line_h + line_gap
    hline_s(draw, banner_h - 12, x0=140, x1=SW - 140, color=_LT_BORDER if is_light else BORDER)
    return new_img


def _draw_share_footer(img, draw, date, lang, caption, theme="dark"):
    is_light = theme == "light"
    y = img.height - 210
    hline_s(draw, y, x0=140, x1=SW - 140, color=_LT_BORDER if is_light else BORDER)
    y += 34
    f_cap = load_font(28, bold=True) if lang == "en" else load_font_cn(26, bold=True)
    centered_s(draw, y, caption, f_cap, _LT_TEXT_SEC if is_light else MUTED)
    y += 48
    centered_s(draw, y, date, load_font(24, mono=True, bold=True), _LT_TEXT_DIM if is_light else DIM)
    y += 56
    # Badge pill, not muted text — first pass blended into the card and read as an
    # afterthought; a solid pill with bold text pops at a glance even at small
    # gallery-thumbnail size. Colors invert per theme so the pill always contrasts
    # against its own card: white pill + dark text on the dark card, dark pill +
    # white text on the light card. Dropped the small logo icon here specifically:
    # _load_logo_cutout's alpha comes from source brightness (bright pixels =
    # opaque), so it's a light-on-dark icon that disappears on a light pill and
    # would need its own dark-on-light asset for the inverse case — bold text
    # alone reads better here regardless of theme. "Baizora" stays Latin-script
    # even on CN cards (brand name, not translated) — matches how the CN cards'
    # own ad-reel CTA says "baizora点com", not a translated domain. Says
    # "downloadable at baizora.com" (not just the bare domain) so the badge
    # itself explains why someone would go there, not just where "there" is.
    brand_text = "Baizora"
    domain_text = "  ·  downloadable at baizora.com" if lang == "en" else "  ·  可在baizora.com下载"
    f_brand = load_font(26, bold=True)
    # CN domain text needs a CJK-capable font — a plain mono font here would
    # render "可在...下载" as tofu boxes, the same class of bug already fixed
    # once for the breakout chart's "前高" peak label.
    f_domain = load_font(22, mono=True, bold=True) if lang == "en" else load_font_cn(20, bold=True)
    brand_w = tw(draw, brand_text, f_brand)
    domain_w = tw(draw, domain_text, f_domain)
    pad_x, pad_y = 20, 11
    pill_w = brand_w + domain_w + pad_x * 2
    pill_h = 48
    px0 = (SW - pill_w) // 2
    pill_bg = _LT_TEXT_PRI if is_light else (255, 255, 255)
    brand_fill = (255, 255, 255) if is_light else (15, 23, 42)
    domain_fill = (203, 213, 225) if is_light else (71, 85, 105)
    draw.rounded_rectangle([px0, y, px0 + pill_w, y + pill_h], radius=pill_h // 2, fill=pill_bg)
    draw.text((px0 + pad_x, y + pad_y - 1), brand_text, font=f_brand, fill=brand_fill)
    draw.text((px0 + pad_x + brand_w, y + pad_y + 2), domain_text, font=f_domain, fill=domain_fill)


_SHARE_CARD_MANIFEST = []  # populated by _save_share_card, drained by write_share_manifest()


def _save_share_card(card_img, ticker, date, lang, caption, out_dir, video_type, idx, theme="light", criteria=None):
    """Stamps the footer onto a copy of an already-rendered card (never mutates the
    frame passed in — the caller renders a fresh theme="light" card specifically
    for this, not the dark video frame; see scene_stock_card's theme docstring)
    and saves it to out_dir/{date}_{video_type}_{lang}_{idx}.png. Filenames are
    date-stamped (unlike the "latest"-only videos) because the homepage gallery
    keeps a rolling week of cards, not just today's — scanner.yml prunes anything
    older than 7 days on each run so the folder/repo doesn't grow unbounded. Also
    records ticker/caption into _SHARE_CARD_MANIFEST so main() can hand
    scanner.yml the metadata needed to build the gallery (this Python code is the
    only place that knows the caption text and which ticker each numbered card is).

    criteria (optional): the screening methodology sentence for this card's
    category (e.g. "Screened from S&P 500 + Nasdaq-100 for..."), drawn as a
    banner above the card via _add_criteria_banner — distinct from caption, which
    is the specific result for this one stock. Kept optional/separate rather than
    folded into caption so the footer's per-stock result line stays unchanged."""
    share_img = card_img.copy()
    if criteria:
        share_img = _add_criteria_banner(share_img, criteria, lang, theme=theme)
    share_draw = ImageDraw.Draw(share_img)
    _draw_share_footer(share_img, share_draw, date, lang, caption, theme=theme)
    filename = f"{date}_{video_type}_{lang}_{idx}.png"
    out_path = Path(out_dir) / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    share_img.save(out_path)
    _SHARE_CARD_MANIFEST.append({
        "file": filename, "date": date, "lang": lang, "video_type": video_type,
        "ticker": ticker, "caption": caption,
    })
    return str(out_path)


def write_share_manifest(out_dir, lang):
    """Dumps this run's _SHARE_CARD_MANIFEST entries to out_dir/_manifest_{lang}.json
    — a small per-invocation fragment (generate_shorts.py only ever builds one
    type/lang per process, and scanner.yml calls it once per language) that
    scanner.yml reads and merges into the rolling 30-day
    data/latest_social_cards_meta.json used by the homepage gallery and the
    subscription-gated chart archive page. Keyed by lang
    (not a single fixed filename) so the EN and CN subprocess runs can't clobber
    each other's fragment before scanner.yml gets to read both."""
    if not _SHARE_CARD_MANIFEST:
        return
    path = Path(out_dir) / f"_manifest_{lang}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_SHARE_CARD_MANIFEST, f, ensure_ascii=False)


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

    if FREE_ACCESS_MODE:
        cta = "100% Free — Sign Up Now" if lang == "en" else "完全免费，立即注册"
    else:
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


# Shortened ad treatment, originally for Sunday/Tuesday/Thursday (user request,
# 2026-08-01) -- skips the 3-part ad reel below entirely and just holds
# scene_ad_short's brand card with a short spoken downloadability line, instead
# of the usual silent 3.0s hold at the very end. Wednesday/Friday are
# unaffected and keep the full build_ad_reel() sequence below. Sunday moved
# OFF this helper 2026-08-22 to its own bespoke closing (see _frame_pchg_sort),
# and Saturday followed the same day (also _frame_pchg_sort, worst.png) --
# only Tuesday/Thursday (1y_vol_peak) still call this one. Durations: real
# edge-tts measurement at SHORTS_TTS_RATE, EN 3.12s / CN 3.12s, +buffer.
# "baizora.com" dropped 2026-08-22 (user request) -- it immediately preceded
# _CLOSING_TAGLINE_EN/CN ("Baizora makes things simple.") with no gap, reading as
# a redundant back-to-back mention (the URL is already shown on-screen throughout
# scene_ad_short's card, see "baizora.com" text drawn at line ~857). Shorter text
# only opens up more silence within the existing 3.5s hold_sec below -- safe by
# construction, no re-measurement needed (padding was already generous, not tight).
_SHORT_AD_LINE_EN = "This chart is free to download."
_SHORT_AD_LINE_CN = "本图表可免费下载。"

# Closing narration every video ends on now (user request, 2026-08-01) -- spoken
# over the same, unchanged scene_ad_short card (previously silent for Monday/
# Wednesday/Friday/Saturday, previously ending on _SHORT_AD_LINE_EN/CN alone for
# Sunday/Tuesday/Thursday). No visual change to the card itself, narration only.
# Real edge-tts measurement at SHORTS_TTS_RATE (re-verified 2026-08-22, isolated
# subprocess per feedback_edge_tts_batch_truncation_bug): EN 1.92s, CN 2.14s.
# Real bug found 2026-08-01: at the original tight +0.3s buffer, this closing
# line -- the single most important one, since the user's explicit ask was for
# every video to END on it -- got clipped or dropped entirely on several
# categories once the new range-narration beats were added, because
# generate_narration() schedules every clip sequentially and small overruns on
# EARLIER beats cascade forward, eating into whatever's scheduled last. Fixed
# at the time by padding this LAST frame generously (6.5s/6.0s) rather than
# trying to trim the exact right amount off upstream beats.
#
# Trimmed back down 2026-08-22 (user noticed ~4s of dead silence at the end of
# every sample video and asked to shorten it) -- since this is the FINAL frame,
# any slack past the real ~2s of audio is pure trailing silence with nothing
# after it to justify holding the frame open, unlike padding on a mid-video
# beat (which "costs nothing visually" since something else plays next either
# way). The 4.5s+ cushion was a one-off defensive patch for a SPECIFIC
# unmeasured beat from 2026-08-01; since then every beat added to every
# category (this whole session included) has been individually edge-tts
# measured with its own small buffer before shipping, so the systemic risk
# that originally justified a multi-second cushion is much lower now.
#
# First cut to 2.5s/2.7s (a normal ~0.5-0.6s buffer, matching everywhere else
# in this file) -- but a real render of Sunday's EN video (best_performer, 10
# scenes incl. this session's new closing beats) then hit a real 0.2s cutoff
# warning on THIS exact scene: cumulative small overruns from several
# pre-existing, already-shipped ticker-narration beats (each individually
# fine, budgeted before this session and never revisited) added up across a
# longer-than-Monday's beat count and ate into the tight margin. Monday's own
# render passed clean at 2.5s/2.7s, proving this is data/category-dependent,
# not a fixed amount -- so the safe fix is a bit more margin here specifically
# (this is the one beat where a cutoff is worst, per the explicit "every video
# must end on this line" requirement), not chasing down every upstream beat's
# exact budget. Settled on ~2s buffer as a middle ground: notably shorter than
# the old 6.5s/6.0s (still saves ~2.5-2.9s per video) while tolerating real
# cascading drift from beats this session didn't touch or re-verify.
_CLOSING_TAGLINE_EN = "Baizora makes things simple."
_CLOSING_TAGLINE_CN = "贝佐拉，化繁为简。"
_CLOSING_TAGLINE_DUR_EN = 3.9
_CLOSING_TAGLINE_DUR_CN = 4.1

# Weekday-specific "we report this regularly" subscribe line (user request,
# 2026-08-22, extended from Monday's near_sma200 category to every category,
# weekends included) -- spoken as an extra beat just before the closing tagline
# in every live category. CN wording is the user's own template ("本频道每周*都
# 会...敬请关注"), applied verbatim per weekday rather than reusing Monday's
# earlier "订阅频道，不要错过" phrasing (retired in favor of this one for
# consistency across all 6). One flat duration per language, sized to the
# longest real weekday line (Tuesday+Thursday's combined line, since that
# category runs on both days and needs one shared sentence) -- all 6 lines
# measured within ~0.5s of each other, not worth a per-line budget.
# EN measured (edge-tts, SHORTS_TTS_RATE): Sun 3.17s, Sat 3.22s, Wed 3.19s,
# Tue+Thu 3.67s, Fri 3.17s, Mon 3.12s -- budget covers the 3.67s max, +buffer.
# CN measured: Mon 3.19s, Tue+Thu 3.65s, Wed 3.24s, Fri 3.31s, Sat 3.36s, Sun
# 3.31s -- budget covers the 3.65s max, +buffer.
_SUBSCRIBE_DUR_EN = 4.0
_SUBSCRIBE_DUR_CN = 3.9
_SUBSCRIBE_MON_EN = "We report this every Monday — subscribe so you don't miss it."
_SUBSCRIBE_MON_CN = "本频道每周一都会带来这个专题，敬请关注。"
_SUBSCRIBE_TUETHU_EN = "We report this every Tuesday and Thursday — subscribe so you don't miss it."
_SUBSCRIBE_TUETHU_CN = "本频道每周二和周四都会带来这个专题，敬请关注。"
_SUBSCRIBE_WED_EN = "We report this every Wednesday — subscribe so you don't miss it."
_SUBSCRIBE_WED_CN = "本频道每周三都会带来这个专题，敬请关注。"
_SUBSCRIBE_FRI_EN = "We report this every Friday — subscribe so you don't miss it."
_SUBSCRIBE_FRI_CN = "本频道每周五都会带来这个专题，敬请关注。"
_SUBSCRIBE_SAT_EN = "We report this every Saturday — subscribe so you don't miss it."
_SUBSCRIBE_SAT_CN = "本频道每周六都会带来这个专题，敬请关注。"
_SUBSCRIBE_SUN_EN = "We report this every Sunday — subscribe so you don't miss it."
_SUBSCRIBE_SUN_CN = "本频道每周日都会带来这个专题，敬请关注。"


def _short_ad_outro_frame(date, lang, subscribe_en=None, subscribe_cn=None):
    """Sunday/Tuesday/Thursday: download-CTA line, then the closing tagline, both
    spoken over the same still image (two narration beats, one frame each, per
    the same multi-beat-over-one-image pattern Friday's spotlight already uses).

    subscribe_en/subscribe_cn (optional, added 2026-08-22): a category- and
    weekday-specific "we report this every X" line (see the _SUBSCRIBE_* module
    constants), spoken as a 3rd beat between the download line and the closing
    tagline. Left optional rather than required so avg_volume -- unreferenced
    in production since the 2026-08-15 rotation rework, still calls this helper
    with no args -- doesn't need one."""
    img = scene_ad_short(date, lang=lang)
    if lang == "cn":
        beats = [(img, 3.5, None, _SHORT_AD_LINE_CN)]
        if subscribe_cn:
            beats.append((img, _SUBSCRIBE_DUR_CN, None, subscribe_cn))
        beats.append((img, _CLOSING_TAGLINE_DUR_CN, None, _CLOSING_TAGLINE_CN))
        return beats
    beats = [(img, 3.5, None, _SHORT_AD_LINE_EN)]
    if subscribe_en:
        beats.append((img, _SUBSCRIBE_DUR_EN, None, subscribe_en))
    beats.append((img, _CLOSING_TAGLINE_DUR_EN, None, _CLOSING_TAGLINE_EN))
    return beats


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

# Reverted to the original platform pitch (trimmed a bit shorter), with a new
# downloadability sentence prepended at the start — a first attempt fully
# replaced this with two short generic sentences, which left ~6.4s of dead air
# (the ad-reel's video clip, ~9.3s, has no narration of its own — the ORIGINAL
# long pitch was deliberately sized to speak across it; a much shorter pitch
# doesn't, and the next line's start time is fixed by frame hold_secs, not by
# when the previous line finishes, so a gap opens up). Combined line measured
# 10.10s at the Shorts TTS rate (+40%) against a 10.83s speaking window (frame4
# hold 1.30s + frame5 video ~9.33s) — comfortable margin, confirmed via the
# actual frame/narration schedule computed by encode(), not guessed.
_AD_PITCH_EN = ("This video's chart is free to download and share, at baizora.com. "
                "Baizora brings every S&P 500 and Nasdaq-100 stock into one table "
                "— volume spikes, key events marked on the trend.")
_AD_PITCH_CN = ("本视频的图表同样可在baizora点com免费下载。"
                 "贝佐拉一张表整合标普500和纳斯达克100全部股票——成交量异动，关键事件标注趋势线。")

# Second, shorter beat for the last ~3-4s of the ad reel (the advertise_2.png still),
# once the main pitch above has already finished — reverted to the original,
# unchanged (the earlier simplification touched this too; user only asked for the
# downloadability sentence to be added at the start of the pitch above).
# "— baizora dot com." dropped 2026-08-22 (user request) -- this beat runs
# immediately into scene_ad_short's _CLOSING_TAGLINE_EN/CN ("Baizora makes things
# simple.") with no gap, and baizora.com was already spoken once in _AD_PITCH_EN
# above, so saying it twice back-to-back right before the closing tagline read as
# redundant. This beat's timing is driven by the still's frame hold_sec, not by
# how long the speech runs (see comment above _AD_PITCH_EN), so a shorter line
# just leaves a bit more silence over the still -- safe by construction.
_AD_PITCH2_EN = "Full stock detail in thirty seconds."
_AD_PITCH2_CN = "半分钟看懂个股全部信息。"


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
    "Today's stock market is showing some major volume spikes, in the S&P 500 and Nasdaq-100.",
    "The stock market just saw some serious volume spikes today, in the S&P 500 and Nasdaq-100.",
    "Big volume can mean big news — here's what's moving today in the S&P 500 and Nasdaq-100.",
]

_HOOK_NARRATION_CN = [
    "今天标普500和纳斯达克100中，出现了几只成交量异动股票。",
    "标普500和纳斯达克100今天出现了几只成交量大幅异动的股票。",
]


def _narrate_ticker_lines(rows, n=5, key="_volMa21Pct"):
    """One short narration line per ticker (not one line for the whole scene) — so
    the table's on-screen time is covered by speech throughout, not just its first
    couple of seconds. Phrasing (leads the pack / follows / rounding out) is meant
    to read as one connected sentence-by-sentence script, not disconnected fragments.
    key is overridable (default is Monday's metric) so the same measured-safe
    template can be reused elsewhere, e.g. Wednesday's price-jump fallback with
    key="PriceChange1D" — same word count/structure, no new TTS measurement needed."""
    lines = []
    for i, row in enumerate(rows[:n]):
        ticker = row.get("Ticker", "")
        v = abs(row.get(key) or 0)
        if i == 0:
            lines.append(f"{ticker} leads the pack, up {v:.0f} percent.")
        elif i == 1:
            lines.append(f"{ticker} follows, up {v:.0f} percent.")
        elif i == n - 1:
            lines.append(f"And rounding things out, {ticker}, also up {v:.0f} percent.")
        else:
            lines.append(f"{ticker} is up {v:.0f} percent.")
    return lines


def _narrate_ticker_lines_cn(rows, n=5, key="_volMa21Pct"):
    lines = []
    for i, row in enumerate(rows[:n]):
        ticker = row.get("Ticker", "")
        v = abs(row.get(key) or 0)
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
    "Best performers in the S&P 500 and Nasdaq-100 over the past {window}.",
    "These stocks led the S&P 500 and Nasdaq-100 over the past {window}.",
]

_HOOK_NARRATION_BEST_CN = [
    "标普500和纳斯达克100中，过去{window}表现最佳的股票。",
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


_HOOK_NARRATION_WORST_EN = [
    "Biggest decliners in the S&P 500 and Nasdaq-100 over the past {window}.",
    "These stocks lagged the S&P 500 and Nasdaq-100 over the past {window}.",
]

_HOOK_NARRATION_WORST_CN = [
    "标普500和纳斯达克100中，过去{window}表现最差的股票。",
]


def _narrate_ticker_lines_worst(rows, key, n=5):
    """Mirrors _narrate_ticker_lines_best exactly, just "down" instead of "up" --
    same reasoning applies (declines are naturally capped near -100%, so no
    hundreds-of-percent overflow risk the way best-performer's gains have)."""
    lines = []
    for i, row in enumerate(rows[:n]):
        ticker = row.get("Ticker", "")
        v = abs(row.get(key) or 0)
        if i == 0:
            lines.append(f"{ticker} leads the decline, down {v:.0f} percent.")
        elif i == 1:
            lines.append(f"{ticker} follows, down {v:.0f} percent.")
        elif i == n - 1:
            lines.append(f"And finally {ticker}, down {v:.0f} percent.")
        else:
            lines.append(f"{ticker} is down {v:.0f} percent.")
    return lines


def _narrate_ticker_lines_worst_cn(rows, key, n=5):
    lines = []
    for i, row in enumerate(rows[:n]):
        ticker = row.get("Ticker", "")
        v = abs(row.get(key) or 0)
        if i == 0:
            lines.append(f"{ticker}领跌，下跌{v:.0f}%。")
        elif i == 1:
            lines.append(f"{ticker}紧随其后，下跌{v:.0f}%。")
        elif i == n - 1:
            lines.append(f"最后是{ticker}，下跌{v:.0f}%。")
        else:
            lines.append(f"{ticker}下跌{v:.0f}%。")
    return lines


_HOOK_NARRATION_PULLBACK_EN = [
    "These S&P 500 and Nasdaq-100 stocks pulled back at least {min_drawdown} percent, then broke out to a new {window} high within the past week.",
    "A real pullback, then a new {window} high, first crossed within the past week — in the S&P 500 and Nasdaq-100.",
]

_HOOK_NARRATION_PULLBACK_CN = [
    "这些标普500和纳斯达克100成分股回调至少{min_drawdown}%，随后在过去一周内首次突破{window}新高。",
    "先经历真实回调，再于一周内首次创下{window}新高——这就是标普500和纳斯达克100今天的主角。",
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
    "Here's the {window} volume record from the last 3 days, in the S&P 500 and Nasdaq-100.",
    "A record volume day often means something big is happening — the {window} record from the last 3 days, in the S&P 500 and Nasdaq-100.",
]

_HOOK_NARRATION_VOL_PEAK_CN = [
    "这些标普500和纳斯达克100成分股，在最近三个交易日内，创下了{window}成交量新纪录。",
    "成交量创新高往往意味着有大事发生——这是标普500和纳斯达克100最近三个交易日内的{window}成交量纪录。",
]


def _narrate_ticker_lines_vol_peak(rows, key, n=5):
    """Ranked by the volume-record day's % volume change. Unlike Monday/Tuesday/
    Wednesday's always-full pools, this category (the stock's biggest volume day in
    the window fell within the last 3 trading sessions) is genuinely rare — most days
    turn up only 1-3 qualifying stocks, sometimes just 1. The "last" index must be
    based on the actual row count (not a fixed n=5), or the closing flourish line
    never triggers on sparse days."""
    n = min(n, len(rows))
    rows = rows[:n]
    lines = []
    for i, row in enumerate(rows):
        ticker = row.get("Ticker", "")
        v = abs(row.get(key) or 0)
        if n == 1:
            lines.append(f"There's only one in the last three days — {ticker}, volume up {v:.0f} percent.")
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
            lines.append(f"近三个交易日只有一只——{ticker}，成交量放大{v:.0f}%。")
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


_HOOK_NARRATION_SMA200_EN = [
    "These S&P 500 and Nasdaq-100 stocks have held above their 200-day average for at least a month, and are now testing it as support.",
    "After holding above their 200-day moving average for at least a month, these S&P 500 and Nasdaq-100 stocks are now pulling back to test it.",
]

_HOOK_NARRATION_SMA200_CN = [
    "这些标普500和纳斯达克100成分股，至少一个月内始终站稳200日均线上方，如今正回踩测试支撑。",
    "至少一个月内始终高于200日均线的标普500和纳斯达克100成分股，如今正回踩均线支撑位。",
]

# Two beats spoken over the same website-screenshot still (same multi-beat-over-
# one-image pattern _short_ad_outro_frame already uses): first explains the
# color convention the real DIST SMA200 column uses (green = still above the
# 200-day average, red = already broken below it -- matches computeSmaDist's
# Above200 color rule in the dashboard's TECH tab, see
# project_tech_view_sma_distance memory), then names the actual column so the
# viewer knows what to look for. Considered visually circling/highlighting the
# column in the screenshot itself instead (pixel-detected its header at
# x~1214-1322, y~0-136 via its accent-blue color), but describing both in
# narration is simpler and doesn't break if the screenshot is ever swapped for
# a different capture.
_SMA200_COLOR_LINE_EN = "Green means it's above the average, red means it's below."
_SMA200_COLOR_LINE_CN = "绿色表示高于均线，红色表示低于均线。"
_SMA200_WEBSITE_LINE_EN = "You can find this yourself — just sort by Dist SMA200 on our website."
_SMA200_WEBSITE_LINE_CN = "你也可以自己查看，在网站上按DIST SMA200排序即可。"

# Spoken over _frame_sma200_sample -- reworded 2026-08-22 (user request) to
# explicitly name "SMA200" (the earlier wording only ever said "the average",
# never the variable itself) and to explicitly flag AVGO as one example, not a
# recommendation of that specific ticker -- per
# feedback_avoid_stock_recommendation_wording, this category screens/reports a
# pattern, it doesn't issue a buy call on the tickers shown. User's own word
# choice, "resistance" (also used in the video/covering/sma200.png cover art) --
# kept as-is rather than substituting "support," even though the mechanics
# shown (price approaching and rebounding from ABOVE) are textbook support
# behavior, since the user chose this wording twice independently.
_SMA200_SAMPLE_LINE_EN = "SMA200 is a strong resistance — AVGO is just one example. Notice how it touches the average and bounces back, again and again."
_SMA200_SAMPLE_LINE_CN = "SMA200是很强的阻力位，AVGO只是一个例子。它多次触及此均线后反弹。"

def _compute_near_sma200(data, window_days=22, band=(0.0, 2.0)):
    """Monday's category (replaces the retired volume_spikes, 2026-08-22, user
    request). A stock qualifies if its close has been at/above its 200-day
    average every session for the trailing window_days=22 sessions AND is
    still at/above it today — i.e. holding the average as support from above,
    not having broken below it. Filtered to a tight 0-2% distance band (user
    request), then ranked by market cap descending (largest first) —
    deliberately NOT by closeness, the band already guarantees "near."

    Narration/criteria copy says "at least one month" (user request,
    2026-08-22). window_days bumped 21 -> 22 to make that claim actually true:
    checked real candles.json dates and 21 trading days only spanned 29
    calendar days (2026-07-22 -> 2026-08-20) -- under a month, which would
    have made "at least one month" an overclaim. 22 trading days spans 30
    calendar days over the same real window -- confirmed via AskUserQuestion
    (offered "bump to 22" vs. "say 'about a month' and leave 21 alone"; user
    picked the bump). A prior attempt made window_days fully dynamic (derived
    from real calendar dates via a new _month_window_days() helper, so it
    could never fall short across any holiday-heavy stretch) -- reverted per
    explicit user feedback ("the video is ok, just change the narrative") that
    this was scope creep on a request that was really just about wording.
    Don't re-add that dynamic-window logic without the user re-raising it.

    This is a fresh Python port of the dashboard TECH tab's computeSmaDist logic
    (see project_tech_view_sma_distance memory) — that helper only runs in the
    browser and has no "stayed above for a month" concept (it's a same-day
    snapshot only), so it couldn't be reused as-is for this video."""
    candles = _load_candles()
    sma = candles.get("sma", {})
    bars_by_ticker = candles.get("data", {})
    candidates = []
    for row in data["data"]:
        ticker = row.get("Ticker", "")
        s200 = sma.get(ticker, {}).get("sma200")
        bars = bars_by_ticker.get(ticker)
        if not s200 or not bars or len(bars) < window_days + 1:
            continue
        recent_closes = [b[3] for b in bars[-(window_days + 1):]]
        recent_sma = s200[-(window_days + 1):]
        if any(v is None for v in recent_sma):
            continue
        prev_closes, prev_sma = recent_closes[:-1], recent_sma[:-1]
        today_close, today_sma = recent_closes[-1], recent_sma[-1]
        if today_sma is None or today_sma <= 0:
            continue
        if not all(c >= s for c, s in zip(prev_closes, prev_sma)):
            continue  # broke below the 200-day average at some point in the trailing month
        if today_close < today_sma:
            continue  # already broken below it today
        dist = (today_close / today_sma - 1) * 100
        if not (band[0] <= dist <= band[1]):
            continue
        row["_smaDistPct"] = round(dist, 2)
        candidates.append(row)
    candidates.sort(key=lambda r: -(r.get("MarketCap") or 0))
    return candidates[:3]


def _narrate_ticker_lines_sma200(rows, key="_smaDistPct"):
    """Custom phrasing (not the generic _narrate_ticker_lines "up N percent"
    template) since this category isn't about a gain — it's about proximity to
    the 200-day average, and rows are ordered by market cap, not by that
    proximity. Row count is data-driven (1-3, same as Thursday's vol-peak
    category) since the 0-2% band can turn up fewer than 3 candidates on a
    given day."""
    n = len(rows)
    lines = []
    for i, row in enumerate(rows):
        ticker = row.get("Ticker", "")
        v = abs(row.get(key) or 0)
        if n == 1:
            lines.append(f"Only one stock qualifies within 0 to 2 percent of its 200-day average today — "
                          f"{ticker}, just {v:.1f} percent above it.")
        elif i == 0:
            # States the actual screening rule (0-2% band) before the ranking
            # rule (largest market cap) -- user request, 2026-08-22: viewers
            # need to hear *why* these 3 first, not just which one is biggest.
            lines.append(f"We screen for stocks within 0 to 2 percent of their 200-day average, then take the "
                          f"3 with the largest market cap. First up, {ticker}, just {v:.1f} percent above it.")
        elif i == n - 1:
            lines.append(f"And rounding it out, {ticker}, {v:.1f} percent above the average.")
        else:
            lines.append(f"{ticker} follows, {v:.1f} percent above its 200-day average.")
    return lines


def _narrate_ticker_lines_sma200_cn(rows, key="_smaDistPct"):
    n = len(rows)
    lines = []
    for i, row in enumerate(rows):
        ticker = row.get("Ticker", "")
        v = abs(row.get(key) or 0)
        if n == 1:
            lines.append(f"今天只有一只股票在200日均线0到2%以内——{ticker}，仅高于均线{v:.1f}%。")
        elif i == 0:
            lines.append(f"我们筛选出距离200日均线0到2%以内的股票，再从中选出市值最大的3只。"
                          f"首先是{ticker}，高于均线{v:.1f}%。")
        elif i == n - 1:
            lines.append(f"最后是{ticker}，高于200日均线{v:.1f}%。")
        else:
            lines.append(f"{ticker}紧随其后，高于均线{v:.1f}%。")
    return lines


def _frame_website_screenshot(lang):
    """Closing 'find it yourself' frame for Monday's SMA200 category — a real,
    full dashboard screenshot (video/sma200_sort.png: nav bar + TECH tab toolbar
    + the actual DIST SMA200-sorted table), not a cropped/staged excerpt. This
    doesn't reuse _frame_ad_asset's fixed 940x1320 portrait box (sized for the
    ad reel's portrait stills/video) — the screenshot itself is wide/short
    (1431x468, a real browser capture), so that box would leave it tiny with a
    huge empty gap top/bottom. Instead: width-driven contain into a near-full-
    width box, pinned close under the heading rather than centered in the full
    canvas (see the y=280 comment below)."""
    heading = "FIND IT ON OUR SITE" if lang == "en" else "在我们网站即可查看"
    img, draw = new_frame_s()
    dot_grid_s(draw)
    f_head = load_headline_font(50) if lang == "en" else load_font_cn(40, bold=True)
    centered_s(draw, 110, heading, f_head, GOLD_LIGHT)
    asset = Image.open(SCRIPT_DIR / "sma200_sort.png").convert("RGB")
    # Near-full-bleed width (not the same generous max_h the portrait ad-reel box
    # gets) and pinned close under the heading, not vertically centered in the
    # full canvas -- a 3:1 landscape image on a 9:16 canvas is always going to
    # leave dead space below it; pinning it high reads as intentional, centering
    # it in a huge empty band read as a rendering mistake in preview.
    box_w, max_h = SW - 40, 700
    nw, nh = _contain_dims(*asset.size, box_w, max_h)
    asset = asset.resize((nw, nh), Image.LANCZOS)
    x = (SW - nw) // 2
    y = 280
    draw.rectangle([x - 8, y - 8, x + nw + 8, y + nh + 8], outline=ELECTRIC, width=4)
    img.paste(asset, (x, y))
    centered_s(draw, y + nh + 60, "baizora.com", load_font(40), ELECTRIC)
    return img


def _frame_sma200_sample(lang):
    """Second closing frame -- a real ticker-detail-modal chart (video/
    sma200_sample.png: AVGO, 6M window, SMA overlay on) so viewers see what the
    pattern actually looks like on a live chart, not just a table of numbers.
    Less extreme aspect ratio than the sort screenshot (972x495, ~2:1 vs ~3:1)
    so it renders a bit larger at the same near-full-bleed width."""
    heading = "SEE IT ON THE CHART" if lang == "en" else "图表上一目了然"
    img, draw = new_frame_s()
    dot_grid_s(draw)
    f_head = load_headline_font(50) if lang == "en" else load_font_cn(40, bold=True)
    centered_s(draw, 110, heading, f_head, GOLD_LIGHT)
    asset = Image.open(SCRIPT_DIR / "sma200_sample.png").convert("RGB")
    box_w, max_h = SW - 40, 900
    nw, nh = _contain_dims(*asset.size, box_w, max_h)
    asset = asset.resize((nw, nh), Image.LANCZOS)
    x = (SW - nw) // 2
    y = 280
    draw.rectangle([x - 8, y - 8, x + nw + 8, y + nh + 8], outline=ELECTRIC, width=4)
    img.paste(asset, (x, y))
    centered_s(draw, y + nh + 60, "baizora.com", load_font(40), ELECTRIC)
    return img


def build_near_sma200_short(data, output, lang="en", share_dir=None):
    """Monday — replaces the retired Volume Spikes category (2026-08-22, user
    request). Top 3 stocks that have held above their 200-day average all month
    and are now within 0-2% of it (testing it as support from above), ranked by
    market cap. See _compute_near_sma200 for the full qualification rule.

    Closing is deliberately minimal (user request, 2026-08-22) — unlike every
    other weekday, this one skips both the full 3-part ad reel AND the short-ad
    "baizora.com" line entirely. Just the real DIST SMA200 dashboard screenshot
    (video/sma200_sort.png, "you can find this yourself on our site") followed
    straight by the standard closing tagline. No separate CTA/signup pitch."""
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    rows = _compute_near_sma200(data)

    if not rows:
        print("No stocks within 0-2% of their 200-day average today — falling back to the price-jump topic.")
        _build_price_jump_fallback(data, output, lang, share_dir, date, date_obj)
        return

    # Durations below = actually-measured edge-tts speech time at SHORTS_TTS_RATE,
    # +~0.2-0.3s buffer each — not estimates (worst-case ticker "GOOGL", worst-case
    # in-band value "2.0", per feedback_measure_tts_duration). Real edge-tts
    # measurement flagged a genuine bug worth remembering: batching many
    # edge_tts.Communicate() calls across separate asyncio.run() invocations in one
    # process silently truncated 2 of 12 CN clips to ~40% of their real length (no
    # exception raised) — re-measuring each line in its own fresh process gave the
    # correct, much longer durations. Don't trust a single batched measurement run
    # for CN without a spot-check in isolation.
    n = len(rows)
    def _dur(i):
        if n == 1:
            # Now states the 0-2% screening rule explicitly (user request,
            # 2026-08-22) -- much longer than a bare "only one qualifies" line.
            # Measured 5.86s/5.57s, +buffer.
            return 6.1 if lang == "en" else 5.8
        if i == 0:
            # States the screening rule (0-2% band) AND the ranking rule
            # (largest market cap) before naming the ticker -- measured
            # 8.23s/8.47s, +buffer.
            return 8.5 if lang == "en" else 8.7
        if i == n - 1:
            return 3.5 if lang == "en" else 3.8
        return 3.5 if lang == "en" else 3.3
    ticker_durs = [_dur(i) for i in range(n)]

    sub_en, sub_cn = "ABOVE 200-DAY AVERAGE", "高于200日均线"
    share_criteria = (
        "Screened from the S&P 500 + Nasdaq-100 for stocks that closed at or above their 200-day moving "
        "average every session for at least the past month, and are now within 0-2% of it — ranked by market cap."
        if lang == "en" else
        "从标普500和纳斯达克100成分股中，筛选出至少一个月内每个交易日收盘价均不低于200日均线、"
        "且目前距离均线在0-2%以内的个股，按市值排序。")

    if lang == "cn":
        ticker_lines = _narrate_ticker_lines_sma200_cn(rows)
        hook_dur, hook_text = 7.0, random.choice(_HOOK_NARRATION_SMA200_CN)  # measured 6.72s/6.36s, +buffer
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        ticker_lines = _narrate_ticker_lines_sma200(rows)
        hook_dur, hook_text = 7.0, random.choice(_HOOK_NARRATION_SMA200_EN)  # measured 6.50s/6.79s, +buffer
        tts_voice = "en-US-ChristopherNeural"

    frames = [
        (scene_hook_generic(date, lang, ["TESTING THEIR", "200-DAY SUPPORT"], ["回踩", "200日均线支撑"],
                            "S&P 500  ·  Nasdaq-100", "标普500 · 纳斯达克100", bg_style="bars"),
         hook_dur, None, hook_text),
    ]
    # One stock at a time (name + distance-from-average number + 1Y trend
    # together) — same per-ticker hero-card shape every other category uses.
    for i, (row, dur, line) in enumerate(zip(rows, ticker_durs, ticker_lines)):
        row["_range_ext"] = _compute_range_extremes(row.get("Ticker", ""))
        card = scene_stock_card(row, i + 1, lang, "_smaDistPct", sub_en, sub_cn, show_sma200=True)
        frames.append((card, dur, None, line))
        range_line = _range_narration_line(row["_range_ext"], lang)
        if range_line:
            frames.append((card, _RANGE_DUR_CN if lang == "cn" else _RANGE_DUR_EN, None, range_line))
        if share_dir:
            v = row.get("_smaDistPct", 0)
            caption = (f"Held above its 200-day average for at least a month, now {v:.1f}% above it" if lang == "en"
                       else f"至少一个月内站稳200日均线上方，如今高出{v:.1f}%")
            light_card = scene_stock_card(row, i + 1, lang, "_smaDistPct", sub_en, sub_cn, theme="light", show_sma200=True)
            _save_share_card(light_card, row.get("Ticker", ""), date, lang, caption, share_dir, "near_sma200", i + 1,
                              criteria=share_criteria)

    # Minimal closing (see docstring) — real DIST SMA200 screenshot, then a real
    # chart showing the pattern, then straight to the closing-tagline brand card
    # (with a category-specific subscribe ask spoken first). No ad reel, no
    # _AD_PITCH/_SHORT_AD_LINE narration at all for this category.
    website_frame = _frame_website_screenshot(lang)
    sample_frame = _frame_sma200_sample(lang)
    ad_card = scene_ad_short(date, lang=lang)
    if lang == "cn":
        # Order swapped 2026-08-22 (user request): name the variable (Dist
        # SMA200) BEFORE explaining what the colors mean, not after.
        frames.append((website_frame, 4.3, None, _SMA200_WEBSITE_LINE_CN))  # measured 4.06s, +buffer
        frames.append((website_frame, 3.4, None, _SMA200_COLOR_LINE_CN))    # measured 3.12s, +buffer
        frames.append((sample_frame, 5.9, None, _SMA200_SAMPLE_LINE_CN))    # measured 5.62s, +buffer
        frames.append((ad_card, _SUBSCRIBE_DUR_CN, None, _SUBSCRIBE_MON_CN))
        frames.append((ad_card, _CLOSING_TAGLINE_DUR_CN, None, _CLOSING_TAGLINE_CN))
    else:
        frames.append((website_frame, 4.3, None, _SMA200_WEBSITE_LINE_EN))  # measured 4.08s, +buffer
        frames.append((website_frame, 3.3, None, _SMA200_COLOR_LINE_EN))    # measured 3.02s, +buffer
        frames.append((sample_frame, 7.7, None, _SMA200_SAMPLE_LINE_EN))    # measured 7.44s, +buffer
        frames.append((ad_card, _SUBSCRIBE_DUR_EN, None, _SUBSCRIBE_MON_EN))
        frames.append((ad_card, _CLOSING_TAGLINE_DUR_EN, None, _CLOSING_TAGLINE_EN))
    encode(frames, output, xfade_frames=3, tts_rate=SHORTS_TTS_RATE, tts_voice=tts_voice)

    cover = cover_path_for("near_sma200" + ("_cn" if lang == "cn" else ""), date_obj)
    if cover:
        _embed_cover(output, cover)


def _frame_pchg_sort(lang, filename):
    """Closing 'find it yourself' frame shared by Sunday's best_performer and
    Saturday's worst_performer — mirrors Monday's _frame_website_screenshot
    (see project_monday_near_sma200_category memory), same near-full-bleed-
    width, pinned-under-the-heading composition. filename picks the real
    screenshot: video/best.png (Sunday, P CHG% sorted descending) or
    video/worst.png (Saturday, same table sorted ascending) — same SCORES
    table + WINDOW toolbar either way, so one frame function covers both;
    only the underlying image differs, the narration spoken over it is
    identical (see _PCHG_VARIABLE_LINE_EN/CN below)."""
    heading = "FIND IT ON OUR SITE" if lang == "en" else "在我们网站即可查看"
    img, draw = new_frame_s()
    dot_grid_s(draw)
    f_head = load_headline_font(50) if lang == "en" else load_font_cn(40, bold=True)
    centered_s(draw, 110, heading, f_head, GOLD_LIGHT)
    asset = Image.open(SCRIPT_DIR / filename).convert("RGB")
    box_w, max_h = SW - 40, 900
    nw, nh = _contain_dims(*asset.size, box_w, max_h)
    asset = asset.resize((nw, nh), Image.LANCZOS)
    x = (SW - nw) // 2
    y = 280
    draw.rectangle([x - 8, y - 8, x + nw + 8, y + nh + 8], outline=ELECTRIC, width=4)
    img.paste(asset, (x, y))
    centered_s(draw, y + nh + 60, "baizora.com", load_font(40), ELECTRIC)
    return img


# Spoken over _frame_pchg_sort -- names the actual column ("P Chg%", used
# across every WINDOW toggle: 1D/2W/1M/3M/6M/9M/1Y) so viewers know they can
# get this same ranking for any timeframe themselves, not just the one
# rotation window this Short happened to show. Category-agnostic wording
# (doesn't say "best"/"worst") so it's shared verbatim by both Sunday and
# Saturday, added 2026-08-22 -- no need to measure/maintain 2 near-identical
# lines. Real edge-tts measurement: EN 4.56s, CN 4.80s, +buffer.
_PCHG_VARIABLE_LINE_EN = "You can find this yourself — sort by P Chg% on our website to get it for any timeframe."
_PCHG_VARIABLE_LINE_CN = "你也可以自己查看，按P CHG%排序，就能方便查看任意时间段的数据。"


def build_best_performer_short(data, output, lang="en", share_dir=None):
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    tf = _tuesday_tf(date)
    key = tf["key"]
    rows = sorted(data["data"], key=lambda r: r.get(key) or -9999, reverse=True)[:3]

    window_en, window_cn = tf["window_en"], tf["window_cn"]
    sub_en, sub_cn = f"OVER THE PAST {window_en.upper()}", f"过去{window_cn}表现"
    share_caption = (f"Top price gainer over the past {window_en}" if lang == "en"
                      else f"过去{window_cn}表现最佳个股")
    share_criteria = (f"Screened from the S&P 500 + Nasdaq-100, ranked by price return over the past {window_en}."
                       if lang == "en" else f"从标普500和纳斯达克100成分股中，按过去{window_cn}涨幅排名筛选。")

    # Durations = actually-measured edge-tts speech time (same measure-don't-guess
    # approach as Monday). Ticker phrasing here is intentionally shorter than Monday's
    # ("leads" not "leads the pack") because best-performer % figures for longer
    # rotation windows (6-Month, 1-Year) can run into the hundreds of percent, and the
    # longer template overran the 30s budget when tested against real data.
    if lang == "cn":
        ticker_lines = _narrate_ticker_lines_best_cn(rows, key, n=3)
        ticker_durs = [3.05, 2.60, 3.40]
        hook_dur = 4.75  # re-measured after adding "S&P 500/Nasdaq-100" mention: 4.42s worst-case, +buffer
        hook_text = random.choice(_HOOK_NARRATION_BEST_CN).format(window=window_cn)
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        ticker_lines = _narrate_ticker_lines_best(rows, key, n=3)
        ticker_durs = [3.40, 2.65, 3.45]
        hook_dur = 4.65  # re-measured after adding "S&P 500/Nasdaq-100" mention: 4.34s worst-case, +buffer
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
        row["_range_ext"] = _compute_range_extremes(row.get("Ticker", ""))
        card = scene_stock_card(row, i + 1, lang, key, sub_en, sub_cn)
        frames.append((card, dur, None, line))
        range_line = _range_narration_line(row["_range_ext"], lang)
        if range_line:
            frames.append((card, _RANGE_DUR_CN if lang == "cn" else _RANGE_DUR_EN, None, range_line))
        if share_dir:
            light_card = scene_stock_card(row, i + 1, lang, key, sub_en, sub_cn, theme="light")
            _save_share_card(light_card, row.get("Ticker", ""), date, lang, share_caption, share_dir, "best_performer", i + 1,
                              criteria=share_criteria)

    # Custom minimal closing (user request, 2026-08-22, "same structure" as
    # Monday's near_sma200 category -- see _frame_website_screenshot /
    # project_monday_near_sma200_category memory): a real dashboard screenshot
    # naming the variable that drives this category, then the subscribe line,
    # then the closing tagline. Replaces the old short-ad treatment
    # (_short_ad_outro_frame's "chart is free to download" line) for Sunday
    # specifically -- Tuesday/Thursday (1y_vol_peak) still use that helper.
    best_frame = _frame_pchg_sort(lang, "best.png")
    ad_card = scene_ad_short(date, lang=lang)
    if lang == "cn":
        frames.append((best_frame, 5.1, None, _PCHG_VARIABLE_LINE_CN))  # measured 4.80s, +buffer
        frames.append((ad_card, _SUBSCRIBE_DUR_CN, None, _SUBSCRIBE_SUN_CN))
        frames.append((ad_card, _CLOSING_TAGLINE_DUR_CN, None, _CLOSING_TAGLINE_CN))
    else:
        # +2s beyond the narration's own buffer (user request, 2026-08-22) --
        # extra silent viewing time on the screenshot itself so it doesn't
        # feel rushed, not a narration-timing fix (real speech is 4.56s).
        frames.append((best_frame, 6.8, None, _PCHG_VARIABLE_LINE_EN))
        frames.append((ad_card, _SUBSCRIBE_DUR_EN, None, _SUBSCRIBE_SUN_EN))
        frames.append((ad_card, _CLOSING_TAGLINE_DUR_EN, None, _CLOSING_TAGLINE_EN))
    encode(frames, output, xfade_frames=3, tts_rate=SHORTS_TTS_RATE, tts_voice=tts_voice)

    cover = cover_path_for("best_performer" + ("_cn" if lang == "cn" else ""), date_obj)
    if cover:
        _embed_cover(output, cover)


def build_worst_performer_short(data, output, lang="en", share_dir=None):
    """Saturday -- mirrors build_best_performer_short exactly (same rotation
    table/window via _tuesday_tf, same card layout), just sorted ascending
    instead of descending. scene_stock_card already colors by sign (row value
    negative -> red) so no card-layout change was needed, only the sort
    direction, narration wording, and hook/caption/criteria text."""
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    tf = _tuesday_tf(date)
    key = tf["key"]
    # Ascending (most negative first). Missing values sorted to the very end
    # regardless of sign, unlike best_performer's `or -9999` trick which would
    # incorrectly rank missing-data rows as "worst" under an ascending sort.
    rows = sorted(data["data"], key=lambda r: r.get(key) if r.get(key) is not None else float("inf"))[:3]

    window_en, window_cn = tf["window_en"], tf["window_cn"]
    sub_en, sub_cn = f"OVER THE PAST {window_en.upper()}", f"过去{window_cn}表现"
    share_caption = (f"Biggest decliner over the past {window_en}" if lang == "en"
                      else f"过去{window_cn}表现最差个股")
    share_criteria = (f"Screened from the S&P 500 + Nasdaq-100 for the largest price decline over the past {window_en}."
                       if lang == "en" else f"从标普500和纳斯达克100成分股中，筛选出过去{window_cn}跌幅最大的个股。")

    # Durations = actually measured edge-tts speech time (SHORTS_TTS_RATE, worst-case
    # window strings "three months"/"twelve months") + ~0.3s buffer, per the
    # measure-don't-guess rule. Ticker-line raw measurements: EN 2.74s/2.52s/2.66s;
    # CN 2.71s/3.19s/3.19s. Hook lines re-measured after adding the "S&P 500 and
    # Nasdaq-100" mention: EN worst-case 4.44s, CN worst-case 4.39s, both +buffer.
    if lang == "cn":
        ticker_lines = _narrate_ticker_lines_worst_cn(rows, key, n=3)
        ticker_durs = [3.0, 3.5, 3.5]
        hook_dur = 4.7
        hook_text = random.choice(_HOOK_NARRATION_WORST_CN).format(window=window_cn)
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        ticker_lines = _narrate_ticker_lines_worst(rows, key, n=3)
        ticker_durs = [3.05, 2.85, 3.0]
        hook_dur = 4.75
        hook_text = random.choice(_HOOK_NARRATION_WORST_EN).format(window=window_en)
        tts_voice = "en-US-ChristopherNeural"

    frames = [
        (scene_hook_generic(date, lang, [f"BIGGEST {tf['label_en'].upper()}", "DECLINERS"],
                            [tf["label_cn"], "表现最差股票"],
                            "S&P 500  ·  Nasdaq-100", "标普500 · 纳斯达克100", bg_style="bars"),
         hook_dur, None, hook_text),
    ]
    for i, (row, dur, line) in enumerate(zip(rows, ticker_durs, ticker_lines)):
        row["_range_ext"] = _compute_range_extremes(row.get("Ticker", ""))
        card = scene_stock_card(row, i + 1, lang, key, sub_en, sub_cn)
        frames.append((card, dur, None, line))
        range_line = _range_narration_line(row["_range_ext"], lang)
        if range_line:
            frames.append((card, _RANGE_DUR_CN if lang == "cn" else _RANGE_DUR_EN, None, range_line))
        if share_dir:
            light_card = scene_stock_card(row, i + 1, lang, key, sub_en, sub_cn, theme="light")
            _save_share_card(light_card, row.get("Ticker", ""), date, lang, share_caption, share_dir, "worst_performer", i + 1,
                              criteria=share_criteria)

    # Custom minimal closing (user request, 2026-08-22, "same for saturday's,
    # using worst.png" -- mirrors Sunday's best_performer closing exactly, see
    # build_best_performer_short / project_regular_cadence_subscribe_line
    # memory): a real dashboard screenshot naming the P Chg% variable, then the
    # subscribe line, then the closing tagline. Replaces the old 3-part ad
    # reel entirely for this category.
    worst_frame = _frame_pchg_sort(lang, "worst.png")
    ad_card = scene_ad_short(date, lang=lang)
    if lang == "cn":
        frames.append((worst_frame, 5.1, None, _PCHG_VARIABLE_LINE_CN))  # measured 4.80s, +buffer
        frames.append((ad_card, _SUBSCRIBE_DUR_CN, None, _SUBSCRIBE_SAT_CN))
        frames.append((ad_card, _CLOSING_TAGLINE_DUR_CN, None, _CLOSING_TAGLINE_CN))
    else:
        # +2s extra silent viewing time, same as Sunday's (user request).
        frames.append((worst_frame, 6.8, None, _PCHG_VARIABLE_LINE_EN))
        frames.append((ad_card, _SUBSCRIBE_DUR_EN, None, _SUBSCRIBE_SAT_EN))
        frames.append((ad_card, _CLOSING_TAGLINE_DUR_EN, None, _CLOSING_TAGLINE_EN))
    encode(frames, output, xfade_frames=3, tts_rate=SHORTS_TTS_RATE, tts_voice=tts_voice)

    cover = cover_path_for("worst_performer" + ("_cn" if lang == "cn" else ""), date_obj)
    if cover:
        _embed_cover(output, cover)


_HOOK_NARRATION_AVGVOL_EN = [
    "Highest average trading volume in the S&P 500 and Nasdaq-100 over the past {window}.",
    "These stocks traded the most shares per day, in the S&P 500 and Nasdaq-100, over the past {window}.",
]

_HOOK_NARRATION_AVGVOL_CN = [
    "标普500和纳斯达克100中，过去{window}日均成交量最高的股票。",
]


def _narrate_ticker_lines_avgvol(rows, key, n=5):
    lines = []
    for i, row in enumerate(rows[:n]):
        ticker = row.get("Ticker", "")
        v = row.get(key) or 0
        if i == 0:
            lines.append(f"{ticker} leads, averaging {v:.1f} million shares a day.")
        elif i == 1:
            lines.append(f"{ticker} follows, averaging {v:.1f} million shares a day.")
        elif i == n - 1:
            lines.append(f"And finally {ticker}, averaging {v:.1f} million shares a day.")
        else:
            lines.append(f"{ticker} averages {v:.1f} million shares a day.")
    return lines


def _narrate_ticker_lines_avgvol_cn(rows, key, n=5):
    lines = []
    for i, row in enumerate(rows[:n]):
        ticker = row.get("Ticker", "")
        v = row.get(key) or 0
        if i == 0:
            lines.append(f"{ticker}领先，日均成交量{v:.1f}百万股。")
        elif i == 1:
            lines.append(f"{ticker}紧随其后，日均成交量{v:.1f}百万股。")
        elif i == n - 1:
            lines.append(f"最后是{ticker}，日均成交量{v:.1f}百万股。")
        else:
            lines.append(f"{ticker}日均成交量{v:.1f}百万股。")
    return lines


def build_avg_volume_short(data, output, lang="en", share_dir=None):
    """Sunday -- highest AVERAGE daily volume over the same 3M/6M/9M/1Y rotation as
    Tuesday/Wednesday/Thursday/Saturday (_tuesday_tf, see
    project-category-video-rotation-unified). Unlike every other ranking category,
    this one isn't a +/- percent off data/latest.json -- it's a raw share count
    computed directly from data/candles.json's daily volume column (same source
    Thursday's real-volume-record detection already reads from, not a
    latest.json-derived proxy), averaged over the window. scene_stock_card's new
    value_fmt="volume" mode displays it as "N.NM" in neutral electric-blue instead
    of pct_str()'s green/red +/- framing, since there's no "good/bad" direction
    for a raw liquidity number."""
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    tf = _tuesday_tf(date)
    window_days = tf["spark_days"]  # None for 1Y = use the full candles.json history
    window_en, window_cn = tf["window_en"], tf["window_cn"]

    candles = _load_candles().get("data", {})
    seen, candidates = set(), []
    for r in data["data"]:
        t = r.get("Ticker", "")
        if t in seen:
            continue
        seen.add(t)
        bars = candles.get(t) or []
        window = bars[-window_days:] if window_days else bars
        if len(window) < 2:
            continue
        vols = [b[4] for b in window]
        r["_avgVolM"] = round(sum(vols) / len(vols) / 1_000_000, 2)
        candidates.append(r)
    candidates.sort(key=lambda r: r["_avgVolM"], reverse=True)
    rows = candidates[:3]
    key = "_avgVolM"

    sub_en, sub_cn = f"AVG DAILY VOLUME  ·  {window_en.upper()}", f"日均成交量 · {window_cn}"
    share_caption = (f"Highest average daily volume over the past {window_en}" if lang == "en"
                      else f"过去{window_cn}日均成交量最高")
    share_criteria = (f"Screened from the S&P 500 + Nasdaq-100 for the highest average daily trading volume "
                       f"over the past {window_en}." if lang == "en" else
                       f"从标普500和纳斯达克100成分股中，筛选出过去{window_cn}日均成交量最高的个股。")

    # Durations = actually measured edge-tts speech time (SHORTS_TTS_RATE, worst-case
    # window "twelve months"/"十二个月", value "145.6 million"/"145.6百万") + buffer.
    if lang == "cn":
        ticker_lines = _narrate_ticker_lines_avgvol_cn(rows, key, n=3)
        ticker_durs = [3.8, 4.35, 4.2]
        hook_dur = 4.8
        hook_text = random.choice(_HOOK_NARRATION_AVGVOL_CN).format(window=window_cn)
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        ticker_lines = _narrate_ticker_lines_avgvol(rows, key, n=3)
        ticker_durs = [4.3, 4.4, 4.4]
        hook_dur = 6.2
        hook_text = random.choice(_HOOK_NARRATION_AVGVOL_EN).format(window=window_en)
        tts_voice = "en-US-ChristopherNeural"

    frames = [
        (scene_hook_generic(date, lang, [f"HIGHEST {tf['label_en'].upper()}", "AVG VOLUME"],
                            [tf["label_cn"], "日均成交量最高"],
                            "S&P 500  ·  Nasdaq-100", "标普500 · 纳斯达克100", bg_style="bars"),
         hook_dur, None, hook_text),
    ]
    for i, (row, dur, line) in enumerate(zip(rows, ticker_durs, ticker_lines)):
        row["_range_ext"] = _compute_range_extremes(row.get("Ticker", ""))
        card = scene_stock_card(row, i + 1, lang, key, sub_en, sub_cn, value_fmt="volume")
        frames.append((card, dur, None, line))
        range_line = _range_narration_line(row["_range_ext"], lang)
        if range_line:
            frames.append((card, _RANGE_DUR_CN if lang == "cn" else _RANGE_DUR_EN, None, range_line))
        if share_dir:
            light_card = scene_stock_card(row, i + 1, lang, key, sub_en, sub_cn, value_fmt="volume", theme="light")
            _save_share_card(light_card, row.get("Ticker", ""), date, lang, share_caption, share_dir, "avg_volume", i + 1,
                              criteria=share_criteria)

    # Shortened ad treatment (user request, 2026-08-01) -- see _short_ad_outro_frame.
    frames += _short_ad_outro_frame(date, lang)
    encode(frames, output, xfade_frames=3, tts_rate=SHORTS_TTS_RATE, tts_voice=tts_voice)

    cover = cover_path_for("avg_volume" + ("_cn" if lang == "cn" else ""), date_obj)
    if cover:
        _embed_cover(output, cover)


_HOOK_NARRATION_PRICE_JUMP_EN = [
    "Today's biggest single-day price jumps in the S&P 500 and Nasdaq-100.",
    "These large-cap stocks are today's top single-day price movers.",
]

_HOOK_NARRATION_PRICE_JUMP_CN = [
    "今日标普500和纳斯达克100中，单日涨幅最大的股票。",
    "这些大盘股是今日单日涨幅最大的个股。",
]


def _build_price_jump_fallback(data, output, lang, share_dir, date, date_obj):
    """Wednesday fallback — used when _compute_breakouts finds no qualifying
    pullback-then-breakout stocks this week (empirically confirmed possible with
    the 1-week lookback: real data hit zero for the 1-Year window the day this was
    built). Falls back to a plain "today's biggest price movers" list (top 3 by
    PriceChange1D) so Wednesday still publishes instead of being skipped — a
    distinct, honestly-labeled topic, not a repackaged breakout claim."""
    rows = sorted(data["data"], key=lambda r: r.get("PriceChange1D") or -9999, reverse=True)[:3]

    sub_en, sub_cn = "TODAY'S PRICE CHANGE", "今日涨幅"
    caption = "Today's biggest single-day price jump" if lang == "en" else "今日单日涨幅最大个股"
    criteria = ("Screened from the S&P 500 + Nasdaq-100 for the largest single-day price gain today." if lang == "en"
                else "从标普500和纳斯达克100成分股中，筛选出今日单日涨幅最大的个股。")

    # Reuses Monday's exact narration template (same word count/structure) via the
    # now-generalized key= param, so its previously-measured durations stay valid —
    # only the hook (genuinely new text) needed fresh edge-tts measurement.
    if lang == "cn":
        ticker_lines = _narrate_ticker_lines_cn(rows, n=3, key="PriceChange1D")
        ticker_durs = [2.8, 3.1, 3.5]
        hook_dur, hook_text = 4.2, random.choice(_HOOK_NARRATION_PRICE_JUMP_CN)  # measured 3.86s/2.78s, +buffer
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        ticker_lines = _narrate_ticker_lines(rows, n=3, key="PriceChange1D")
        ticker_durs = [3.2, 2.7, 3.8]
        hook_dur, hook_text = 4.6, random.choice(_HOOK_NARRATION_PRICE_JUMP_EN)  # measured 4.34s/3.36s, +buffer
        tts_voice = "en-US-ChristopherNeural"

    frames = [
        (scene_hook_generic(date, lang, ["BIGGEST PRICE", "JUMPS TODAY"], ["今日", "最大涨幅"],
                            "S&P 500  ·  Nasdaq-100", "标普500 · 纳斯达克100", bg_style="bull"),
         hook_dur, None, hook_text),
    ]
    for i, (row, dur, line) in enumerate(zip(rows, ticker_durs, ticker_lines)):
        row["_range_ext"] = _compute_range_extremes(row.get("Ticker", ""))
        card = scene_stock_card(row, i + 1, lang, "PriceChange1D", sub_en, sub_cn)
        frames.append((card, dur, None, line))
        range_line = _range_narration_line(row["_range_ext"], lang)
        if range_line:
            frames.append((card, _RANGE_DUR_CN if lang == "cn" else _RANGE_DUR_EN, None, range_line))
        if share_dir:
            light_card = scene_stock_card(row, i + 1, lang, "PriceChange1D", sub_en, sub_cn, theme="light")
            _save_share_card(light_card, row.get("Ticker", ""), date, lang, caption, share_dir, "price_jump", i + 1,
                              criteria=criteria)

    ad_entries = build_ad_reel(lang=lang)
    ad_pitch = _AD_PITCH_CN if lang == "cn" else _AD_PITCH_EN
    ad_pitch2 = _AD_PITCH2_CN if lang == "cn" else _AD_PITCH2_EN
    first = ad_entries[0]
    ad_entries[0] = (first[0], first[1], first[2], ad_pitch)
    last = ad_entries[-1]
    ad_entries[-1] = (last[0], last[1], last[2], ad_pitch2)
    frames += ad_entries
    frames.append((scene_ad_short(date, lang=lang),
                   _CLOSING_TAGLINE_DUR_CN if lang == "cn" else _CLOSING_TAGLINE_DUR_EN, None,
                   _CLOSING_TAGLINE_CN if lang == "cn" else _CLOSING_TAGLINE_EN))
    encode(frames, output, xfade_frames=3, tts_rate=SHORTS_TTS_RATE, tts_voice=tts_voice)

    cover = cover_path_for("near_sma200" + ("_cn" if lang == "cn" else ""), date_obj)
    if cover:
        _embed_cover(output, cover)


def build_6m_breakout_short(data, output, lang="en", share_dir=None):
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    tf = _wednesday_tf(date)
    # 1-week lookback (not the long-form video's default 2-week) — this Short runs
    # weekly, and a 2-week window risked re-selecting the same breakout ticker two
    # weeks running.
    breakouts = _compute_breakouts(data["data"], tf, lookback_days=5)
    # Ranked by pullback depth (not today's move) — the story is "how far did it fall
    # before reclaiming a new high", which is the stat that was missing from narration.
    breakouts.sort(key=lambda x: x.get("_drawdown") or 0, reverse=True)
    rows = breakouts[:3]

    if not rows:
        print(f"No {tf['label_en']} breakout stocks today — falling back to today's biggest price movers.")
        _build_price_jump_fallback(data, output, lang, share_dir, date, date_obj)
        return

    # Cards display the pullback magnitude (as a negative %, in red) rather than
    # today's price move — that's the headline stat for this category.
    for r in rows:
        r["_drawdown_display"] = -abs(r.get("_drawdown") or 0)

    window_en, window_cn = tf["window_en"], tf["window_cn"]
    label_en, label_cn = tf["label_en"], tf["label_cn"]

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
        # Re-measured after adding the "标普500和纳斯达克100" mention — edge-tts at
        # SHORTS_TTS_RATE, worst-case window_cn ("十二个月"), min_drawdown=10: 6.43s/6.43s, +buffer.
        hook_dur = 6.75
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
        # Re-measured after adding the "S&P 500 and Nasdaq-100" mention — edge-tts at
        # SHORTS_TTS_RATE, worst-case window_en ("twelve months"), min_drawdown=10: 6.72s/6.41s, +buffer.
        hook_dur = 7.05
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
        row["_range_ext"] = _compute_range_extremes(row.get("Ticker", ""))
        # Per-row real drawdown (e.g. "-32% DECLINE"), not the generic min_drawdown
        # screening threshold (e.g. "10%+ DECLINE") — the threshold is just the
        # cutoff for making the list, the real number is the actual story for this
        # specific stock and is already the big colored number above this caption,
        # so this just states it in words too rather than a repeated generic rule.
        dd_abs = abs(row.get("_drawdown") or 0)
        row_sub_en = f"{row.get('_drawdown_display', 0):.0f}% DECLINE, HIGH CROSSED IN PAST WEEK"
        row_sub_cn = f"跌{dd_abs:.0f}%，一周内首次突破新高"
        # "PREV HIGH" / "前高" rather than tf's timeframe-specific header (e.g. "1Y
        # HIGH") — the hook scene already states the timeframe ("1-YEAR HIGH"), so
        # the marker itself just needs to say what the dot/line actually is.
        card = scene_stock_card(row, i + 1, lang, "_drawdown_display", row_sub_en, row_sub_cn, gold_leader=False,
                                 peak_label_en="PREV HIGH", peak_label_cn="前高")
        frames.append((card, dur, None, line))
        range_line = _range_narration_line(row["_range_ext"], lang)
        if range_line:
            frames.append((card, _RANGE_DUR_CN if lang == "cn" else _RANGE_DUR_EN, None, range_line))
        if share_dir:
            # label_en (e.g. "1-Year") not window_en (e.g. "twelve months") before
            # "high" — window_en reads fine in "over the past twelve months" but
            # turns into bad grammar ("twelve months high") as a compound modifier.
            row_share_caption = (f"Real {dd_abs:.0f}% pullback, new {label_en.lower()} high within the past week" if lang == "en"
                                  else f"回调{dd_abs:.0f}%，一周内首次创{window_cn}新高")
            row_share_criteria = (
                f"Screened from the S&P 500 + Nasdaq-100 for stocks that fell {tf['min_drawdown']}%+ from a high, "
                f"then broke out to a new {window_en} high within the past week." if lang == "en" else
                f"从标普500和纳斯达克100成分股中，筛选出曾回调{tf['min_drawdown']}%以上、并在过去一周内首次突破{window_cn}新高的个股。")
            light_card = scene_stock_card(row, i + 1, lang, "_drawdown_display", row_sub_en, row_sub_cn, gold_leader=False,
                                           peak_label_en="PREV HIGH", peak_label_cn="前高", theme="light")
            _save_share_card(light_card, row.get("Ticker", ""), date, lang, row_share_caption, share_dir, "6m_breakout", i + 1,
                              criteria=row_share_criteria)

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
    # Wednesday-specific subscribe line, added 2026-08-22 (see _SUBSCRIBE_WED_EN/CN)
    # -- extra beat over the same closing brand card, before the closing tagline.
    ad_card = scene_ad_short(date, lang=lang)
    frames.append((ad_card, _SUBSCRIBE_DUR_CN if lang == "cn" else _SUBSCRIBE_DUR_EN, None,
                   _SUBSCRIBE_WED_CN if lang == "cn" else _SUBSCRIBE_WED_EN))
    frames.append((ad_card,
                   _CLOSING_TAGLINE_DUR_CN if lang == "cn" else _CLOSING_TAGLINE_DUR_EN, None,
                   _CLOSING_TAGLINE_CN if lang == "cn" else _CLOSING_TAGLINE_EN))
    encode(frames, output, xfade_frames=3, tts_rate=SHORTS_TTS_RATE, tts_voice=tts_voice)

    cover = cover_path_for("6m_breakout" + ("_cn" if lang == "cn" else ""), date_obj)
    if cover:
        _embed_cover(output, cover)


def build_1y_vol_peak_short(data, output, lang="en", share_dir=None):
    """Thursday — stocks setting a new N-month volume record within the last 3
    trading days. Unlike Monday/Tuesday/Wednesday's always-full pools, this event
    is genuinely rare: most days only turn up 1-3 qualifying stocks (sometimes
    exactly 1), so both the table and
    the trend-scene count adapt to however many rows actually exist today, rather
    than assuming 5. Purely a volume story (no "bounce back" framing — that's
    Wednesday's price-pullback category; there's no equivalent volume concept)."""
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    tf = _thursday_tf(date)
    window_days = tf["spark_days"]  # None for 1Y = use the full candles.json history

    # Real absolute-volume-record detection, read directly from candles.json's raw
    # daily volume — not a proxy off data/latest.json's "MaxVolumeChange" field.
    # That field (see calculate_period_metrics in scanner_tiingo.py) is the biggest
    # single-day CHANGE in volume vs. the previous day, which is a different thing
    # from an absolute record: a stock can post a huge jump off a quiet prior day
    # without its volume ever being the window's highest. This surfaced as a real
    # bug — FRT's 1Y example showed a taller bar earlier in the window than the
    # day this category was calling a "record."
    #
    # Peak day allowed to fall anywhere in the last 3 trading sessions (not
    # strictly today) — requiring an exact-today record was too rare and risked
    # zero qualifying stocks on most days. The displayed % is the peak day's
    # volume vs. the window's own average volume (excluding the peak day itself,
    # so the record day doesn't inflate its own baseline) — not vs. the previous
    # record — matching how Monday's volume-spikes category expresses its %.
    candles = _load_candles().get("data", {})
    seen, candidates = set(), []
    for r in data["data"]:
        t = r.get("Ticker", "")
        if t in seen:
            continue
        seen.add(t)
        bars = candles.get(t) or []
        window = bars[-window_days:] if window_days else bars
        n = len(window)
        if n < 2:
            continue
        vols = [b[4] for b in window]
        peak_idx = max(range(n), key=lambda i: vols[i])
        if peak_idx < n - 3:
            continue  # the window's highest-volume day wasn't in the last 3 sessions
        other_vols = vols[:peak_idx] + vols[peak_idx + 1:]
        if not other_vols:
            continue
        avg_vol = sum(other_vols) / len(other_vols)
        if avg_vol <= 0:
            continue
        r["_volPeakPct"] = round((vols[peak_idx] / avg_vol - 1) * 100, 2)
        candidates.append(r)
    candidates.sort(key=lambda r: r["_volPeakPct"], reverse=True)
    rows = candidates[:3]
    vol_key = "_volPeakPct"

    if not rows:
        print(f"No {tf['label_en']} volume-record stocks today — falling back to Monday's near-SMA200 topic.")
        build_near_sma200_short(data, output, lang=lang, share_dir=share_dir)
        return

    window_en, window_cn = tf["window_en"], tf["window_cn"]
    sub_en, sub_cn = f"VS {window_en.upper()} AVERAGE VOLUME", f"对比{window_cn}平均成交量"
    share_criteria = (
        f"Screened from the S&P 500 + Nasdaq-100 for stocks that hit their highest trading volume of the "
        f"past {window_en} within the last 3 trading days — shown as % above the period's average volume."
        if lang == "en" else
        f"从标普500和纳斯达克100成分股中，筛选出近3个交易日内成交量创下过去{window_cn}新高的个股，"
        f"涨幅按对比该时段平均成交量计算。")

    if lang == "cn":
        ticker_lines = _narrate_ticker_lines_vol_peak_cn(rows, vol_key)
        hook_dur = 7.45  # re-measured after adding "标普500和纳斯达克100" mention (worst-case "十二个月": 7.13s), +buffer
        hook_text = random.choice(_HOOK_NARRATION_VOL_PEAK_CN).format(window=window_cn)
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        ticker_lines = _narrate_ticker_lines_vol_peak(rows, vol_key)
        hook_dur = 7.55  # re-measured after adding "S&P 500 and Nasdaq-100" mention (worst-case "twelve months": 7.20s), +buffer
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
        row["_range_ext"] = _compute_range_extremes(row.get("Ticker", ""))
        card = scene_stock_card(row, i + 1, lang, vol_key, sub_en, sub_cn)
        frames.append((card, dur, None, line))
        range_line = _range_narration_line(row["_range_ext"], lang)
        if range_line:
            frames.append((card, _RANGE_DUR_CN if lang == "cn" else _RANGE_DUR_EN, None, range_line))
        if share_dir:
            # Per-row caption (pct varies by ticker), same pattern as Wednesday's
            # per-row real-drawdown caption. States "(past 3 days)" here too, not
            # just in the criteria banner — the peak day isn't always literally
            # today (see the peak_idx < n - 3 relaxation above), so the footer
            # description needs the same caveat as the banner to stay accurate.
            pct = row["_volPeakPct"]
            row_share_caption = (f"New {window_en} volume record (past 3 days), {pct:.0f}% above average volume" if lang == "en"
                                  else f"创{window_cn}新高（最近3日内），较平均成交量高出{pct:.0f}%")
            light_card = scene_stock_card(row, i + 1, lang, vol_key, sub_en, sub_cn, theme="light")
            _save_share_card(light_card, row.get("Ticker", ""), date, lang, row_share_caption, share_dir, "1y_vol_peak", i + 1,
                              criteria=share_criteria)

    # Shortened ad treatment (user request, 2026-08-01) -- see _short_ad_outro_frame.
    # This category runs both Tuesday and Thursday (see the 2026-08-15 rework
    # commit "Rework Tuesday/Sunday category video rotation"), so the subscribe
    # line names both days rather than picking one (see _SUBSCRIBE_TUETHU_EN/CN).
    frames += _short_ad_outro_frame(date, lang, subscribe_en=_SUBSCRIBE_TUETHU_EN, subscribe_cn=_SUBSCRIBE_TUETHU_CN)
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


def _pick_spotlight_rotation(members, lang, date=""):
    """Cycle through spotlight candidates in ticker-alphabetical order instead of
    picking independently at random each Friday — with only a handful of
    candidates on file at a time, independent random picks can (and did, per
    LITE showing up 3 of 5 real Fridays) land on the same ticker repeatedly by
    chance instead of eventually covering everyone. State is per-language
    (data/spotlight_rotation_{lang}.json) since EN and CN Shorts are generated
    as separate runs and shouldn't share a rotation position.

    Robust to the candidate list changing week to week (new joins added, old
    ones aging out past the 2-year window in _get_verified_members): position
    is tracked by ticker name, not list index, and if the last-picked ticker
    is no longer a candidate, rotation resumes at the next ticker alphabetically
    after it (wrapping to the start if none), rather than resetting to 0."""
    state_path = SCRIPT_DIR.parent / "data" / f"spotlight_rotation_{lang}.json"
    sorted_members = sorted(members, key=lambda m: m["ticker"])
    tickers = [m["ticker"] for m in sorted_members]

    last_ticker = None
    try:
        last_ticker = json.loads(state_path.read_text(encoding="utf-8")).get("last_ticker")
    except Exception:
        pass

    if last_ticker in tickers:
        idx = (tickers.index(last_ticker) + 1) % len(tickers)
    elif last_ticker:
        idx = next((i for i, t in enumerate(tickers) if t > last_ticker), 0)
    else:
        idx = 0

    picked = sorted_members[idx]
    try:
        state_path.write_text(json.dumps({"last_ticker": picked["ticker"], "date": date}),
                               encoding="utf-8")
    except Exception:
        pass
    return picked


def build_index_spotlight_short(data, output, lang="en", share_dir=None):
    """Friday — spotlights one recently-added S&P 500 / Nasdaq-100 member and its
    price since joining. Unlike Monday-Thursday's ranked lists, this is a single-
    stock feature, so the same spotlight image is narrated across two frames
    instead of a table across five. Candidate is chosen by rotation, not
    independently at random — see _pick_spotlight_rotation()."""
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    members = _get_verified_members(data)

    if not members:
        print("No new index members found today, skipping Short.")
        return

    member = _pick_spotlight_rotation(members, lang, date)
    ticker = member["ticker"]
    index_name = member["index_name"]
    index_cn = "纳斯达克100" if "Nasdaq" in index_name else "标普500"
    bdays = member["bdays_since_join"]
    perf = member["perf_since_join"]
    max_gain = member.get("max_gain_since_join", perf)
    max_loss = member.get("max_loss_since_join", perf)

    spotlight_img = scene_member_spotlight_short(member, date, lang)
    if share_dir:
        # Single card, not [:3] — Friday only ever spotlights the one member picked
        # above, and the share image reuses that exact same pick (not a re-roll),
        # rendered a second time in the light theme for the share image only.
        share_caption = (f"Newest member of the {index_name}" if lang == "en"
                          else f"{index_cn}最新成分股")
        share_criteria = (f"Spotlighting a stock that recently joined the {index_name}, tracked from Baizora's "
                           f"index-membership monitor." if lang == "en" else
                           f"聚焦最近加入{index_cn}的新成分股，数据来自贝佐拉的指数成分股监测。")
        light_spotlight = scene_member_spotlight_short(member, date, lang, theme="light")
        _save_share_card(light_spotlight, ticker, date, lang, share_caption, share_dir, "index_spotlight", 1,
                          criteria=share_criteria)

    # Durations = actually-measured edge-tts speech time at SHORTS_TTS_RATE (see
    # measure_fri.py in scratch), +buffer. spot_max/spot_min durations measured
    # separately (worst-case 3-digit percent, e.g. "142 percent"): EN 3.38s/2.62s,
    # CN 2.40s/2.09s, +buffer.
    if lang == "cn":
        hook_dur = 4.2
        hook_text = random.choice(_HOOK_NARRATION_SPOTLIGHT_CN)
        spot1_line = f"{ticker}在{bdays}个交易日前加入{index_cn}。"
        spot1_dur = 3.5
        spot_max_line = f"最高曾上涨{max_gain:.0f}%。"
        spot_max_dur = 2.7
        spot_min_line = f"最低曾下跌{abs(max_loss):.0f}%。"
        spot_min_dur = 2.5
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
        spot_max_line = f"At its highest, it was up {max_gain:.0f} percent since joining."
        spot_max_dur = 3.7
        spot_min_line = f"At its lowest, it was down {abs(max_loss):.0f} percent."
        spot_min_dur = 3.0
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
        (spotlight_img, spot_max_dur, None, spot_max_line),
        (spotlight_img, spot_min_dur, None, spot_min_line),
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
    # Friday-specific subscribe line, added 2026-08-22 (see _SUBSCRIBE_FRI_EN/CN)
    # -- extra beat over the same closing brand card, before the closing tagline.
    ad_card = scene_ad_short(date, lang=lang)
    frames.append((ad_card, _SUBSCRIBE_DUR_CN if lang == "cn" else _SUBSCRIBE_DUR_EN, None,
                   _SUBSCRIBE_FRI_CN if lang == "cn" else _SUBSCRIBE_FRI_EN))
    frames.append((ad_card,
                   _CLOSING_TAGLINE_DUR_CN if lang == "cn" else _CLOSING_TAGLINE_DUR_EN, None,
                   _CLOSING_TAGLINE_CN if lang == "cn" else _CLOSING_TAGLINE_EN))
    encode(frames, output, xfade_frames=3, tts_rate=SHORTS_TTS_RATE, tts_voice=tts_voice)

    cover = cover_path_for("index_spotlight" + ("_cn" if lang == "cn" else ""), date_obj)
    if cover:
        _embed_cover(output, cover)


BUILDERS = {
    "near_sma200": build_near_sma200_short,
    "best_performer": build_best_performer_short,
    "6m_breakout": build_6m_breakout_short,
    "1y_vol_peak": build_1y_vol_peak_short,
    "index_spotlight": build_index_spotlight_short,
    "worst_performer": build_worst_performer_short,
    "avg_volume": build_avg_volume_short,
}


def main():
    ap = argparse.ArgumentParser(description="Baizora YouTube Shorts Generator")
    ap.add_argument("--type", required=True, choices=list(BUILDERS))
    ap.add_argument("--output", default=None)
    ap.add_argument("--data", default=None)
    ap.add_argument("--lang", default="en", choices=["en", "cn"])
    ap.add_argument("--share-dir", default=None,
                     help="If set, also saves standalone watermarked PNGs of each "
                          "card (for the homepage's downloadable-chart gallery) "
                          "into this directory, plus a _manifest_{lang}.json fragment.")
    ap.add_argument("--date-override", default=None,
                     help="Overrides data['date'] (YYYY-MM-DD) for on-screen date text, "
                          "share-card filenames, and cover-art day rotation. Needed for "
                          "weekend category videos (worst_performer/avg_volume), which "
                          "reuse Friday's data/latest.json (SKIP_SCAN=1 on weekends) but "
                          "should still show the actual Saturday/Sunday calendar date, "
                          "not Friday's.")
    args = ap.parse_args()

    data_path = Path(args.data) if args.data else DATA_FILE
    with open(data_path) as f:
        data = json.load(f)
    if args.date_override:
        data["date"] = args.date_override

    output = args.output or str(SCRIPT_DIR / f"{args.type}_short.mp4")
    Path(output).parent.mkdir(parents=True, exist_ok=True)

    print(f"Building SHORT [{args.type}]  ->  {output}")
    BUILDERS[args.type](data, output, lang=args.lang, share_dir=args.share_dir)
    if args.share_dir:
        write_share_manifest(args.share_dir, args.lang)


if __name__ == "__main__":
    main()
