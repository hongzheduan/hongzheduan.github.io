#!/usr/bin/env python3
"""
Baizora YouTube Thumbnail Generator
Generates a branded 1280x720 PNG "cover" for a video, explicitly set via the YouTube
API instead of leaving YouTube to auto-pick a frame from the video (which tends to land
on a plain chart/table scene — not attention-grabbing).

Style deliberately matches high-performing finance-YouTube thumbnails: heavy condensed
headline (Anton, bundled in video/fonts/ so it renders identically on the GitHub Actions
Ubuntu runner that actually generates videos, not just locally on Windows), a chart-texture
background, an icon accent, and a colored caption banner — not a plain data screenshot.

10 templates total, 2 per weekday video type, alternating week-to-week so the channel
doesn't look repetitive but each thumbnail still matches its video's actual content.

Usage (standalone preview):
    py generate_thumbnail.py --video-type volume_spikes --date 2026-07-06 --variant 0 \
        --output preview.png
"""

import argparse
import datetime
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from generate_video import (
    NAVY, ELEC_BRIGHT, GOLD, GOLD_LIGHT, GREEN, RED, BRIGHT_GREEN, BRIGHT_RED,
    WHITE, MUTED, DIM, tw, th,
)

SCRIPT_DIR = Path(__file__).parent
FONTS_DIR = SCRIPT_DIR / "fonts"

TW, TH = 1280, 720  # YouTube's recommended thumbnail size (16:9)

# Extra colors beyond generate_video.py's palette, used only for thumbnail accents.
ORANGE = (251, 146, 60)
PURPLE = (192, 91, 247)
TEAL = (45, 212, 191)
DARK_RED = (35, 10, 10)
DARK_GREEN = (8, 28, 18)


_headline_font_cache = {}


def load_headline_font(size):
    """Anton (OFL-licensed, bundled) — heavy condensed display font for the big
    thumbnail keyword. Falls back to generate_video.py's bold font if the bundled
    file is somehow missing so this never hard-crashes the pipeline."""
    if size in _headline_font_cache:
        return _headline_font_cache[size]
    from PIL import ImageFont
    path = FONTS_DIR / "Anton-Regular.ttf"
    if path.exists():
        font = ImageFont.truetype(str(path), size)
    else:
        from generate_video import load_font
        font = load_font(size, bold=True)
    _headline_font_cache[size] = font
    return font


def _new_canvas(base=NAVY):
    img = Image.new("RGB", (TW, TH), base)
    return img, ImageDraw.Draw(img)


def _center_text(draw, cx, y, text, font, fill):
    w = tw(draw, text, font)
    draw.text((cx - w // 2, y), text, font=font, fill=fill)


def _wrapped_headline(draw, cx, y, lines, font, fill, line_gap=6):
    """Draws each string in `lines` centered on its own row, stacked with line_gap px
    between rows. Returns the y just below the last line."""
    for line in lines:
        h = th(draw, line, font)
        _center_text(draw, cx, y, line, font, fill)
        y += h + line_gap
    return y


def _caption_banner(draw, cx, y, text, bg, fg, font, pad_x=26, pad_y=12):
    w = tw(draw, text, font)
    h = th(draw, text, font)
    box = [cx - w // 2 - pad_x, y, cx + w // 2 + pad_x, y + h + pad_y * 2]
    draw.rectangle(box, fill=bg)
    draw.text((cx - w // 2, y + pad_y - 2), text, font=font, fill=fg)
    return box[3]


def _logo_tiny(draw, x, y, size=20):
    from generate_video import load_font
    f = load_font(size, serif=True)
    draw.text((x, y), "Baiz", font=f, fill=WHITE)
    draw.text((x + tw(draw, "Baiz", f), y), "ora", font=f, fill=ELEC_BRIGHT)


def _glow_line(img, draw, points, color, width=5, glow_radius=14):
    """Draws a line twice — a soft blurred wide glow pass, then a crisp thin pass on
    top — the 'neon chart line' look used throughout the reference thumbnails."""
    overlay = Image.new("RGB", img.size, (0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.line(points, fill=color, width=width + 10, joint="curve")
    overlay = overlay.filter(ImageFilter.GaussianBlur(glow_radius))
    img.paste(Image.composite(overlay, img, overlay.convert("L").point(lambda p: min(255, p * 3))), (0, 0))
    draw.line(points, fill=color, width=width, joint="curve")


# ── Background chart textures ─────────────────────────────────────────────────────

def _bg_volume_bars(img, draw, base_color, region=(0, 0, TW, TH), n=40, seed=7):
    x0, y0, x1, y1 = region
    w = (x1 - x0) / n
    rnd = _lcg(seed)
    baseline = y1 - 10
    for i in range(n):
        h = 30 + int(rnd() * (y1 - y0 - 60))
        if i % 6 == 0:
            h = int(h * 1.6)
        bx0 = x0 + i * w + 2
        bx1 = bx0 + w - 4
        c = GOLD if i % 6 == 0 else base_color
        draw.rectangle([bx0, baseline - h, bx1, baseline], fill=c)


def _lcg(seed):
    state = [seed * 2654435761 % (2**32)]
    def nxt():
        state[0] = (state[0] * 1103515245 + 12345) % (2**31)
        return (state[0] % 10000) / 10000
    return nxt


def _drawdown_recovery_curve(frac, dip_frac=0.4, low=0.15, start=0.55, end=1.0):
    """0 (frac=0) -> start, falls to low at dip_frac, then climbs past start to a new
    high (end) by frac=1. Continuous at the dip point — no jump — since both branches
    evaluate to exactly `low` there."""
    if frac <= dip_frac:
        t = frac / dip_frac
        return start - t * (start - low)
    t = (frac - dip_frac) / (1 - dip_frac)
    return low + t * (end - low)


def _bg_line_up(img, draw, color, region=(0, 0, TW, TH), n=14, seed=3, dip=False):
    x0, y0, x1, y1 = region
    rnd = _lcg(seed)
    pts = []
    for i in range(n):
        frac = i / (n - 1)
        base = _drawdown_recovery_curve(frac) if dip else (0.15 + frac * 0.7)
        jitter = (rnd() - 0.5) * 0.1
        val = max(0.03, min(0.97, base + jitter))
        x = x0 + frac * (x1 - x0)
        y = y1 - val * (y1 - y0)
        pts.append((x, y))
    _glow_line(img, draw, pts, color, width=6, glow_radius=16)


def _bg_candlesticks(img, draw, region=(0, 0, TW, TH), n=22, seed=11, recovery=False):
    x0, y0, x1, y1 = region
    rnd = _lcg(seed)
    w = (x1 - x0) / n
    for i in range(n):
        frac = i / (n - 1)
        base = _drawdown_recovery_curve(frac) if recovery else (0.2 + frac * 0.55)
        cy_center = y1 - base * (y1 - y0)
        body_h = 14 + int(rnd() * 55)
        wick = body_h + int(rnd() * 30)
        cx = x0 + i * w + w / 2
        cy = cy_center + (rnd() - 0.5) * 30
        up = rnd() > (0.35 if (recovery and frac < 0.4) else 0.45)
        color = BRIGHT_GREEN if up else BRIGHT_RED
        draw.line([(cx, cy - wick / 2), (cx, cy + wick / 2)], fill=color, width=3)
        draw.rectangle([cx - w * 0.32, cy - body_h / 2, cx + w * 0.32, cy + body_h / 2], fill=color)


def _bg_sparkle_burst(draw, cx, cy, size, color, points=4):
    for k in range(points):
        ang = math.pi / 2 * k + math.pi / 4
        x2, y2 = cx + math.cos(ang) * size, cy + math.sin(ang) * size
        draw.line([(cx, cy), (x2, y2)], fill=color, width=4)
    draw.line([(cx - size * 0.55, cy), (cx + size * 0.55, cy)], fill=color, width=3)
    draw.line([(cx, cy - size * 0.55), (cx, cy + size * 0.55)], fill=color, width=3)


# ── Icon accents ───────────────────────────────────────────────────────────────────

def _icon_arrow_up(draw, cx, cy, size, color):
    draw.polygon([
        (cx, cy - size), (cx - size * 0.55, cy), (cx - size * 0.22, cy),
        (cx - size * 0.22, cy + size), (cx + size * 0.22, cy + size),
        (cx + size * 0.22, cy), (cx + size * 0.55, cy),
    ], fill=color)


def _icon_rocket(draw, cx, cy, size, flame_color=ORANGE):
    body_w = size * 0.5
    draw.polygon([(cx, cy - size), (cx - body_w, cy + size * 0.5), (cx + body_w, cy + size * 0.5)], fill=WHITE)
    draw.ellipse([cx - body_w * 0.4, cy - size * 0.1, cx + body_w * 0.4, cy + size * 0.1 + body_w * 0.8],
                 fill=ELEC_BRIGHT)
    draw.polygon([(cx - body_w, cy + size * 0.2), (cx - body_w * 1.6, cy + size * 0.7), (cx - body_w * 0.3, cy + size * 0.55)], fill=RED)
    draw.polygon([(cx + body_w, cy + size * 0.2), (cx + body_w * 1.6, cy + size * 0.7), (cx + body_w * 0.3, cy + size * 0.55)], fill=RED)
    draw.polygon([
        (cx - body_w * 0.5, cy + size * 0.5), (cx + body_w * 0.5, cy + size * 0.5),
        (cx + body_w * 0.3, cy + size * 1.3), (cx, cy + size * 1.7), (cx - body_w * 0.3, cy + size * 1.3),
    ], fill=flame_color)


def _icon_crown(draw, cx, cy, size, color, gem_color=None):
    """5-point crown — a clean, unambiguous 'market leader' icon (an earlier bull-
    silhouette attempt didn't read recognizably at thumbnail scale; this does)."""
    gem_color = gem_color or NAVY
    base_w = size * 1.8
    base_h = size * 0.4
    spikes_x = [cx - base_w * 0.5, cx - base_w * 0.25, cx, cx + base_w * 0.25, cx + base_w * 0.5]
    heights = [size * 0.55, size * 0.95, size * 1.3, size * 0.95, size * 0.55]
    pts = [(spikes_x[0], cy)]
    for i, (x, h) in enumerate(zip(spikes_x, heights)):
        pts.append((x, cy - h))
        if i < len(spikes_x) - 1:
            valley_x = (x + spikes_x[i + 1]) / 2
            valley_h = min(h, heights[i + 1]) * 0.3
            pts.append((valley_x, cy - valley_h))
    pts.append((spikes_x[-1], cy))
    draw.polygon(pts, fill=color)
    draw.rectangle([cx - base_w * 0.5, cy, cx + base_w * 0.5, cy + base_h], fill=color)
    for x, h in zip(spikes_x, heights):
        r = size * 0.09
        draw.ellipse([x - r, cy - h - r, x + r, cy - h + r], fill=gem_color)


def _icon_bank(draw, cx, cy, size, color=(148, 163, 184)):
    draw.polygon([(cx - size, cy), (cx, cy - size * 0.7), (cx + size, cy)], fill=color)
    draw.rectangle([cx - size, cy, cx + size, cy + size * 0.1], fill=color)
    for i, lx in enumerate([-0.75, -0.35, 0.05, 0.45]):
        x = cx + lx * size
        draw.rectangle([x, cy + size * 0.15, x + size * 0.28, cy + size * 1.0], fill=color)
    draw.rectangle([cx - size * 1.05, cy + size * 1.05, cx + size * 1.05, cy + size * 1.2], fill=color)


# ── Shared frame chrome ────────────────────────────────────────────────────────────

def _finish(draw, date_str, accent):
    draw.rectangle([0, 0, TW - 1, TH - 1], outline=accent, width=6)
    _logo_tiny(draw, 26, TH - 44)
    from generate_video import load_font
    draw.text((TW - 150, TH - 40), date_str, font=load_font(16), fill=DIM)


# ── 10 templates, 2 per weekday video type ─────────────────────────────────────────

def thumb_volume_a(label, date, lang="en"):
    img, draw = _new_canvas(DARK_GREEN)
    _bg_volume_bars(img, draw, (20, 90, 55), region=(0, TH - 260, TW, TH - 20))
    _icon_arrow_up(draw, TW - 160, 210, 90, BRIGHT_GREEN)
    f = load_headline_font(108)
    _wrapped_headline(draw, 470, 90, ["BIGGEST VOLUME", "SPIKES"], f, GOLD_LIGHT, line_gap=4)
    _caption_banner(draw, 470, 320, "TODAY'S UNUSUAL ACTIVITY", ELECTRIC := (30, 64, 175), WHITE,
                    load_headline_font(30))
    _finish(draw, date, BRIGHT_GREEN)
    return img


def thumb_volume_b(label, date, lang="en"):
    img, draw = _new_canvas((20, 10, 10))
    _bg_volume_bars(img, draw, (70, 20, 15), region=(0, TH - 260, TW, TH - 20), seed=19)
    _icon_rocket(draw, TW - 170, TH // 2 - 20, 95)
    f = load_headline_font(102)
    _wrapped_headline(draw, 460, 100, ["STOCKS EXPLODING", "IN VOLUME"], f, ORANGE, line_gap=4)
    _caption_banner(draw, 460, 330, "TODAY", RED, WHITE, load_headline_font(34))
    _finish(draw, date, ORANGE)
    return img


def thumb_best_a(label, date, lang="en"):
    img, draw = _new_canvas((6, 22, 16))
    _bg_line_up(img, draw, BRIGHT_GREEN, region=(0, 60, TW, TH - 40))
    f = load_headline_font(112)
    _wrapped_headline(draw, TW // 2, 90, ["TOP WINNERS"], f, GOLD_LIGHT)
    _caption_banner(draw, TW // 2, 290, f"{label.upper()} PERFORMANCE", (21, 128, 61), WHITE,
                    load_headline_font(32))
    _finish(draw, date, BRIGHT_GREEN)
    return img


def thumb_best_b(label, date, lang="en"):
    img, draw = _new_canvas((6, 22, 16))
    _bg_line_up(img, draw, BRIGHT_GREEN, region=(0, 60, TW, TH - 40), seed=41)
    f = load_headline_font(100)
    _wrapped_headline(draw, TW // 2, 80, ["LARGE-CAP", "GAINERS"], f, WHITE, line_gap=4)
    _caption_banner(draw, TW // 2, 320, f"BEST RETURNS — {label.upper()}", (21, 128, 61), WHITE,
                    load_headline_font(28))
    _finish(draw, date, BRIGHT_GREEN)
    return img


def thumb_breakout_a(label, date, lang="en"):
    img, draw = _new_canvas((10, 16, 26))
    _bg_candlesticks(img, draw, region=(0, 80, TW, TH - 40))
    dash_y = 260
    for x in range(40, TW - 40, 40):
        draw.line([(x, dash_y), (x + 22, dash_y)], fill=GOLD_LIGHT, width=3)
    f = load_headline_font(104)
    _wrapped_headline(draw, TW // 2, 90, ["BREAKOUT STOCKS"], f, GOLD_LIGHT)
    _caption_banner(draw, TW // 2, 300, f"NEW {label.upper()} HIGHS", WHITE, (10, 16, 26),
                    load_headline_font(30))
    _finish(draw, date, GOLD_LIGHT)
    return img


def thumb_breakout_b(label, date, lang="en"):
    img, draw = _new_canvas((16, 12, 10))
    _bg_candlesticks(img, draw, region=(0, 80, TW, TH - 40), recovery=True, seed=53)
    _icon_arrow_up(draw, TW - 150, TH // 2 + 40, 80, BRIGHT_GREEN)
    f = load_headline_font(104)
    _wrapped_headline(draw, 460, 90, ["PULLBACK", "RECOVERIES"], f, ORANGE, line_gap=4)
    _caption_banner(draw, 460, 320, "BOUNCING BACK STRONG", WHITE, (16, 12, 10), load_headline_font(26))
    _finish(draw, date, ORANGE)
    return img


def thumb_volpeak_a(label, date, lang="en"):
    img, draw = _new_canvas((18, 8, 26))
    _bg_volume_bars(img, draw, (110, 40, 160), region=(0, TH - 260, TW, TH - 20), seed=29)
    _bg_sparkle_burst(draw, TW - 150, 160, 46, WHITE)
    f = load_headline_font(90)
    _wrapped_headline(draw, TW // 2, 70, ["RECORD VOLUME", "STOCKS"], f, PURPLE, line_gap=4)
    _caption_banner(draw, TW // 2, 300, f"NEW {label.upper()} HIGH", GOLD, (18, 8, 26), load_headline_font(28))
    _finish(draw, date, PURPLE)
    return img


def thumb_volpeak_b(label, date, lang="en"):
    img, draw = _new_canvas((6, 22, 16))
    _bg_line_up(img, draw, BRIGHT_GREEN, region=(0, 60, TW, TH - 40), seed=61)
    _bg_sparkle_burst(draw, TW - 200, 110, 40, WHITE)
    f = load_headline_font(112)
    _wrapped_headline(draw, TW // 2, 90, ["NEW HIGH STOCKS"], f, WHITE)
    _caption_banner(draw, TW // 2, 300, "BREAKING OUT NOW", (21, 128, 61), WHITE, load_headline_font(30))
    _finish(draw, date, BRIGHT_GREEN)
    return img


def thumb_index_a(label, date, lang="en"):
    img, draw = _new_canvas((8, 16, 26))
    _icon_bank(draw, TW - 220, TH // 2 + 20, 110)
    f = load_headline_font(100)
    _wrapped_headline(draw, 430, 90, ["NEW INDEX", "MEMBERS"], f, TEAL, line_gap=4)
    _caption_banner(draw, 430, 320, "HOW ARE THEY PERFORMING?", WHITE, (8, 16, 26), load_headline_font(26))
    from generate_video import load_font
    draw.text((280, 420), "S&P 500", font=load_font(18, bold=True), fill=DIM)
    draw.text((530, 420), "NASDAQ-100", font=load_font(18, bold=True), fill=DIM)
    _finish(draw, date, TEAL)
    return img


def thumb_index_b(label, date, lang="en"):
    img, draw = _new_canvas((14, 12, 8))
    _icon_crown(draw, TW - 220, TH - 230, 105, GOLD_LIGHT)
    f = load_headline_font(108)
    _wrapped_headline(draw, TW // 2, 90, ["MARKET LEADERS", "TODAY"], f, GOLD_LIGHT, line_gap=4)
    _caption_banner(draw, TW // 2, 310, "THE STRONGEST STOCKS", WHITE, (14, 12, 8), load_headline_font(28))
    _finish(draw, date, GOLD_LIGHT)
    return img


# ── Rotation ────────────────────────────────────────────────────────────────────────

_WEEKDAY_TEMPLATES = {
    "volume_spikes":  [thumb_volume_a, thumb_volume_b],
    "best_performer": [thumb_best_a, thumb_best_b],
    "6m_breakout":    [thumb_breakout_a, thumb_breakout_b],
    "1y_vol_peak":    [thumb_volpeak_a, thumb_volpeak_b],
    "index_spotlight": [thumb_index_a, thumb_index_b],
}


def variant_for_date(date_obj):
    """Alternates between each weekday's 2 templates by ISO week parity, so the same
    weekday's video doesn't look identical every single week."""
    return date_obj.isocalendar()[1] % 2


def build_thumbnail(video_type, label, date_str, variant=None, lang="en"):
    base_type = video_type[:-3] if video_type.endswith("_cn") else video_type
    templates = _WEEKDAY_TEMPLATES.get(base_type)
    if not templates:
        raise ValueError(f"No thumbnail templates for video type: {video_type}")
    if variant is None:
        variant = variant_for_date(datetime.date.fromisoformat(date_str))
    fn = templates[variant % len(templates)]
    return fn(label, date_str, lang=lang)


def save_thumbnail(path, video_type, label, date_str, variant=None, lang="en"):
    img = build_thumbnail(video_type, label, date_str, variant=variant, lang=lang)
    img.save(path, "PNG")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-type", required=True,
                    choices=list(_WEEKDAY_TEMPLATES.keys()) + [k + "_cn" for k in _WEEKDAY_TEMPLATES])
    ap.add_argument("--label", default="9-Month", help="rotating timeframe label, e.g. 9-Month")
    ap.add_argument("--date", required=True)
    ap.add_argument("--variant", type=int, default=None, help="0 or 1; default = auto by week parity")
    ap.add_argument("--lang", default="en", choices=["en", "cn"])
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    save_thumbnail(args.output, args.video_type, args.label, args.date,
                    variant=args.variant, lang=args.lang)
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
