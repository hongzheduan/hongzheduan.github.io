#!/usr/bin/env python3
"""
Stock Market Recap (internally "market wrap"): general stock-market video, every Wednesday and Friday.

Landscape (1920x1080) regular YouTube video of about 2 minutes, EN only. It was a
vertical Short at launch (2026-10-21); the user asked 2026-10-22 for a ~2-minute
video under the channel's Videos tab instead, so it is landscape (YouTube files any
16:9 upload as a regular video, whatever its length) and the scenes were expanded:
  1. Hook        "STOCK MARKET RECAP", weekday eyebrow, date, what's covered
  2. Indexes     S&P 500 (via SPY) + Nasdaq-100 (via QQQ) day change, breadth of each
  3. Sectors     S&P 500 sectors, market-cap-weighted 1-day change
  4. Gainers     top 5 S&P 500 / Nasdaq-100 stocks by 1-day price change
  5. Decliners   bottom 5, same universe
  6. Volume      top 5 by volume vs its 21-day average
  7. Headlines   up to MAX_STORIES of the day's market news, curated by Claude Haiku
                 (same curate_stories() as the Market Pulse news video)
  8. Outro       brand card + subscribe line (info-only, no website mention)

All numbers come straight from data/latest.json and are narrated by template,
never by the LLM, so nothing numeric can be hallucinated. The LLM only touches
the headline section; if that call fails the video still ships without it
(about 1:45 instead of about 2:05).

Skips (writes no output file) unless data/latest.json holds the requested
date's finished session (not the midday snapshot). On a market holiday or a
late scan the workflow's retry cron tries again later.

Also writes <output>.png (the hook frame), uploaded as the video's thumbnail.

Usage:
    python generate_market_wrap.py --date 2026-10-21 --output video/market_wrap.mp4
"""
import argparse
import datetime
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from generate_video import (  # noqa: E402
    load_font, tw, th, encode, pct_str, new_frame, centered, hline, _wrap_text, _short_name,
    W, H, NAVY, WHITE, MUTED, DIM, GOLD_LIGHT, ELECTRIC, ELEC_BRIGHT, NAVY_LIGHT,
    BRIGHT_GREEN, BRIGHT_RED,
)
from generate_shorts import _diamond, _paste_cover, SW  # noqa: E402
from generate_thumbnail import load_headline_font  # noqa: E402
from generate_news_report import (  # noqa: E402
    curate_stories, measure_tts_seconds, news_bg_path_for_story, news_bg_path_for_day,
    NEWS_TTS_VOICE_EN,
)

DATA_DIR = SCRIPT_DIR.parent / "data"

MAX_STORIES = 3   # ~105s of data scenes + ~7s per story lands near 2 minutes
N_MOVERS = 5        # rows shown and narrated per movers / volume scene
N_SECTORS_SPOKEN = 2  # leaders and laggards named in the sector narration

# A touch slower than the Shorts' +20%: this is a sit-down recap, not a quick cut.
WRAP_TTS_RATE = "+10%"
XFADE_FRAMES = 12   # 0.4s cross-fade between scenes

# The News_*.png photos are portrait (~0.563). A full-height panel of that width
# on the right of the 16:9 frame shows the whole photo with no crop.
PHOTO_W = round(H * 0.5625)
PHOTO_X = W - PHOTO_W
TEXT_X = 120

_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_SUBSCRIBE_EN = ("That's the stock market recap. We recap the market every Wednesday and Friday. "
                 "Subscribe to the Baizora channel for more.")


_TRIM_DIR = Path(tempfile.mkdtemp(prefix="market_wrap_bg_"))


def _trimmed_bg(path, border=8):
    """Some News_*.png photos carry a thin white strip along an edge. Crop a
    few px off every side first."""
    out = _TRIM_DIR / Path(path).name
    if not out.exists():
        im = Image.open(path)
        w, h = im.size
        im.crop((border, border, w - border, h - border)).save(out)
    return str(out)


def _eyebrow(draw, text, y):
    """Centered badge on the vertical 1080-wide canvas. Kept for
    generate_stock_profile.py, which imports it; this video uses _eyebrow_at()."""
    f = load_font(26, mono=True)
    ew = tw(draw, text, f)
    ex = (SW - (ew + 90)) // 2 + 46
    draw.rectangle([ex - 66, y - 16, ex + ew + 24, y + 44], fill=NAVY_LIGHT, outline=ELECTRIC, width=2)
    _diamond(draw, ex - 38, y + 14, 12, ELEC_BRIGHT)
    draw.text((ex, y), text, font=f, fill=ELEC_BRIGHT)


def _eyebrow_at(draw, text, x, y):
    """Left-aligned badge, its outer left edge at x."""
    f = load_font(24, mono=True)
    ew = tw(draw, text, f)
    tx = x + 60
    draw.rectangle([x, y - 14, tx + ew + 24, y + 42], fill=NAVY_LIGHT, outline=ELECTRIC, width=2)
    _diamond(draw, x + 30, y + 14, 11, ELEC_BRIGHT)
    draw.text((tx, y), text, font=f, fill=ELEC_BRIGHT)


def _dot_grid(draw, x1=W, spacing=60, color=(20, 35, 65)):
    for gx in range(spacing, x1, spacing):
        for gy in range(spacing, H, spacing):
            draw.ellipse([gx - 1, gy - 1, gx + 1, gy + 1], fill=color)


def _photo_panel(img, bg_path):
    """Photo in the right-hand panel, with a soft fade into the navy on its left edge."""
    _paste_cover(img, bg_path, (PHOTO_X, 0, W, H), valign="center")
    fade_w = 220
    grad = Image.new("L", (fade_w, 1))
    for x in range(fade_w):
        grad.putpixel((x, 0), int(255 * (1 - x / fade_w)))
    grad = grad.resize((fade_w, H))
    navy = Image.new("RGB", (fade_w, H), NAVY)
    region = img.crop((PHOTO_X, 0, PHOTO_X + fade_w, H))
    img.paste(Image.composite(navy, region, grad), (PHOTO_X, 0))


def _scene_header(draw, eyebrow, subtitle):
    _eyebrow_at(draw, eyebrow, TEXT_X, 80)
    if subtitle:
        draw.text((TEXT_X, 150), subtitle, font=load_font(28), fill=MUTED)


def _signed(v, digits=1):
    """'up 1.2 percent' / 'down 0.4 percent' / 'flat'. Whole numbers drop the
    '.0' so TTS doesn't read 'nine point zero'."""
    if v is None or round(abs(v), digits) == 0:
        return "flat"
    num = f"{abs(v):.{digits}f}".removesuffix(".0")
    return f"{'up' if v > 0 else 'down'} {num} percent"


def _move_words(v, up="rose", down="fell"):
    """'rose 0.42 percent' / 'fell 1.10 percent' / 'was flat'."""
    if v is None or abs(v) < 0.005:
        return "was flat"
    return f"{up if v > 0 else down} {abs(v):.2f} percent"


def _pct_color(v):
    return BRIGHT_GREEN if (v or 0) >= 0 else BRIGHT_RED


def _display_name(r, limit=34):
    name = (r.get("CompanyName") or "").strip()
    if name.isupper():
        # word by word so "AT&T" stays upper instead of becoming "At&T"
        name = " ".join(w if "&" in w else w.title() for w in name.split())
    name = _short_name(name, r.get("Ticker", ""))
    return name if len(name) <= limit else name[:limit - 3].rstrip() + "..."


def _join_spoken(parts):
    if len(parts) > 1:
        parts = parts[:-1] + ["and " + parts[-1]]
    return ", ".join(parts)


# ── Data ────────────────────────────────────────────────────────────────

def load_session(date_str):
    """Returns latest.json's payload only if it is date_str's finished session."""
    with open(DATA_DIR / "latest.json", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("date") != date_str or data.get("midday"):
        print(f"latest.json is {data.get('date')} (midday={data.get('midday')}), "
              f"not the finished {date_str} session; skipping.")
        return None
    return data


def market_snapshot(data):
    rows = data.get("data", [])
    stale = set(data.get("staleTickers") or [])
    by_ticker = {r.get("Ticker"): r for r in rows}
    stocks = [r for r in rows
              if (r.get("InSP500") or r.get("InNASDAQ100"))
              and r.get("PriceChange1D") is not None
              and r.get("Ticker") not in stale]
    sp = [r for r in stocks if r.get("InSP500")]
    ndx = [r for r in stocks if r.get("InNASDAQ100")]
    ranked = sorted(stocks, key=lambda r: r["PriceChange1D"], reverse=True)
    spy, qqq = by_ticker.get("SPY"), by_ticker.get("QQQ")

    # Market-cap-weighted 1-day change per S&P 500 sector.
    sectors = {}
    for r in sp:
        sec, cap = r.get("Sector"), r.get("MarketCap") or 0
        if not sec or sec == "Unknown" or cap <= 0:
            continue
        s = sectors.setdefault(sec, [0.0, 0.0, 0])
        s[0] += r["PriceChange1D"] * cap
        s[1] += cap
        s[2] += 1
    sector_moves = sorted(((sec, v[0] / v[1], v[2]) for sec, v in sectors.items()),
                          key=lambda t: t[1], reverse=True)

    vol = sorted((r for r in stocks if r.get("VolumeVsMA21_1D")),
                 key=lambda r: r["VolumeVsMA21_1D"], reverse=True)

    return {
        "spy": spy.get("PriceChange1D") if spy else None,
        "qqq": qqq.get("PriceChange1D") if qqq else None,
        "sp_up": sum(1 for r in sp if r["PriceChange1D"] > 0),
        "sp_down": sum(1 for r in sp if r["PriceChange1D"] < 0),
        "sp_total": len(sp),
        "ndx_up": sum(1 for r in ndx if r["PriceChange1D"] > 0),
        "ndx_down": sum(1 for r in ndx if r["PriceChange1D"] < 0),
        "ndx_total": len(ndx),
        "sectors": sector_moves,
        "gainers": [r for r in ranked if r["PriceChange1D"] > 0][:N_MOVERS],
        "losers": [r for r in reversed(ranked) if r["PriceChange1D"] < 0][:N_MOVERS],
        "volume": vol[:N_MOVERS],
    }


# ── Scenes ──────────────────────────────────────────────────────────────

def scene_hook(date_obj, date_str):
    img, draw = new_frame()
    _dot_grid(draw, x1=PHOTO_X)
    _photo_panel(img, _trimmed_bg(news_bg_path_for_day(date_obj)))
    _eyebrow_at(draw, f"{_WEEKDAYS[date_obj.weekday()].upper()} EDITION", TEXT_X, 250)
    f_head = load_headline_font(170)
    y = 350
    draw.text((TEXT_X, y), "STOCK MARKET", font=f_head, fill=WHITE)
    y += draw.textbbox((0, 0), "STOCK MARKET", font=f_head)[3] + 10
    draw.text((TEXT_X, y), "RECAP", font=f_head, fill=GOLD_LIGHT)
    y += draw.textbbox((0, 0), "RECAP", font=f_head)[3] + 50
    draw.text((TEXT_X, y), "S&P 500  ·  Nasdaq-100", font=load_font(44), fill=WHITE)
    y += 80
    long_date = f"{_WEEKDAYS[date_obj.weekday()]}, {_MONTHS[date_obj.month - 1]} {date_obj.day}, {date_obj.year}"
    draw.text((TEXT_X, y), long_date, font=load_font(34, mono=True), fill=MUTED)
    return img


def _breadth_bar(draw, x0, x1, y, up, down, total):
    bar_h = 36
    total = max(total, 1)
    draw.rectangle([x0, y, x1, y + bar_h], fill=NAVY_LIGHT)
    if up:
        draw.rectangle([x0, y, x0 + round((x1 - x0) * up / total), y + bar_h], fill=BRIGHT_GREEN)
    if down:
        draw.rectangle([x1 - round((x1 - x0) * down / total), y, x1, y + bar_h], fill=BRIGHT_RED)
    y += bar_h + 22
    f_cnt = load_font(34, bold=True)
    draw.text((x0, y), f"{up} up", font=f_cnt, fill=BRIGHT_GREEN)
    dtxt = f"{down} down"
    draw.text((x1 - tw(draw, dtxt, f_cnt), y), dtxt, font=f_cnt, fill=BRIGHT_RED)


def scene_indexes(snap):
    img, draw = new_frame()
    _dot_grid(draw)
    _scene_header(draw, "THE MARKET TODAY", "Index change on the day and how many members closed higher")

    f_label = load_font(46, bold=True)
    f_pct = load_headline_font(190)
    f_via = load_font(24, mono=True)
    col_w = 700
    gap = (W - 2 * col_w) // 3
    cols = (
        ("S&P 500", "via SPY", snap["spy"], snap["sp_up"], snap["sp_down"], snap["sp_total"]),
        ("NASDAQ-100", "via QQQ", snap["qqq"], snap["ndx_up"], snap["ndx_down"], snap["ndx_total"]),
    )
    for i, (label, via, v, up, down, total) in enumerate(cols):
        x0 = gap + i * (col_w + gap)
        cx = x0 + col_w // 2
        y = 290
        draw.text((cx - tw(draw, label, f_label) // 2, y), label, font=f_label, fill=MUTED)
        y += 80
        txt = pct_str(v) if v is not None else "n/a"
        draw.text((cx - tw(draw, txt, f_pct) // 2, y), txt, font=f_pct, fill=_pct_color(v))
        y += draw.textbbox((0, 0), txt, font=f_pct)[3] + 20
        draw.text((cx - tw(draw, via, f_via) // 2, y), via, font=f_via, fill=DIM)
        y += 90
        bl = "BREADTH"
        f_bl = load_font(24, mono=True)
        draw.text((cx - tw(draw, bl, f_bl) // 2, y), bl, font=f_bl, fill=MUTED)
        _breadth_bar(draw, x0, x0 + col_w, y + 50, up, down, total)
    return img


def scene_sectors(sectors):
    img, draw = new_frame()
    _dot_grid(draw)
    _scene_header(draw, "SECTORS", "S&P 500 sectors  ·  1-day change, weighted by market cap")

    n = len(sectors)
    top, bottom = 240, H - 90
    row_h = min(68, (bottom - top) // max(n, 1))
    label_x1 = 640           # sector names right-aligned to this x
    zero_x = 1180            # bar baseline
    # px per percentage point: the longest bar on each side, plus its value
    # label, has to fit between the baseline and the names / the right margin.
    neg_room = zero_x - label_x1 - 190
    pos_room = W - TEXT_X - zero_x - 170
    max_pos = max([v for _, v, _ in sectors if v > 0] or [0.01])
    max_neg = max([-v for _, v, _ in sectors if v < 0] or [0.01])
    scale = min(pos_room / max_pos, neg_room / max_neg)
    f_lbl = load_font(32, bold=True)
    f_val = load_font(30, mono=True)
    draw.line([(zero_x, top - 10), (zero_x, top + n * row_h)], fill=DIM, width=2)
    for i, (sec, v, _) in enumerate(sectors):
        y = top + i * row_h
        mid = y + row_h // 2
        draw.text((label_x1 - tw(draw, sec, f_lbl), mid - 20), sec, font=f_lbl, fill=WHITE)
        bar = max(round(abs(v) * scale), 3)
        bx0, bx1 = (zero_x, zero_x + bar) if v >= 0 else (zero_x - bar, zero_x)
        draw.rectangle([bx0, mid - 18, bx1, mid + 18], fill=_pct_color(v))
        ptxt = pct_str(v)
        # value sits past the bar's end, on the side the bar points to
        tx = bx1 + 18 if v >= 0 else bx0 - 18 - tw(draw, ptxt, f_val)
        draw.text((tx, mid - 18), ptxt, font=f_val, fill=_pct_color(v))
    return img


def scene_movers(rows, title, subtitle, value_fn, value_color_fn):
    """5-row table: rank, ticker + name, sector, price, 1D change, and a
    right-hand highlight column given by value_fn."""
    img, draw = new_frame()
    _dot_grid(draw)
    _scene_header(draw, title, subtitle)

    f_rank = load_font(30, mono=True)
    f_tkr = load_headline_font(70)
    f_name = load_font(28)
    f_cell = load_font(32)
    f_hi = load_headline_font(70)
    f_hdr = load_font(20, mono=True)
    x_rank, x_tkr, x_sec, x_price, x_r = TEXT_X, 210, 860, 1300, W - TEXT_X
    y = 230
    for txt, x in (("SECTOR", x_sec), ("PRICE", x_price)):
        draw.text((x, y), txt, font=f_hdr, fill=DIM)
    row_h = 150
    y += 36
    for i, r in enumerate(rows):
        hline(draw, y, x0=TEXT_X, x1=W - TEXT_X)
        top = y + 24
        draw.text((x_rank, top + 22), f"{i + 1:02d}", font=f_rank, fill=DIM)
        draw.text((x_tkr, top - 4), r.get("Ticker", ""), font=f_tkr, fill=WHITE)
        draw.text((x_tkr + 2, top + 84), _display_name(r), font=f_name, fill=MUTED)
        sec = r.get("Sector") or ""
        if sec and sec != "Unknown":
            draw.text((x_sec, top + 22), sec, font=f_cell, fill=MUTED)
        price = r.get("Price")
        if price is not None:
            draw.text((x_price, top + 22), f"${price:,.2f}", font=f_cell, fill=WHITE)
        hi = value_fn(r)
        draw.text((x_r - tw(draw, hi, f_hi), top - 4), hi, font=f_hi, fill=value_color_fn(r))
        y += row_h
    hline(draw, y, x0=TEXT_X, x1=W - TEXT_X)
    return img


def scene_news_card(idx, total, headline, source, bg_path):
    img, draw = new_frame()
    _dot_grid(draw, x1=PHOTO_X)
    _photo_panel(img, bg_path)
    _eyebrow_at(draw, "MARKET NEWS", TEXT_X, 110)
    f_idx = load_font(26, mono=True)
    itxt = f"{idx} / {total}"
    draw.text((PHOTO_X - 140 - tw(draw, itxt, f_idx), 110), itxt, font=f_idx, fill=DIM)

    max_w = PHOTO_X - TEXT_X - 140
    f_head = load_font(64, bold=True)
    lines = _wrap_text(draw, headline, f_head, max_w)
    if len(lines) > 5:
        f_head = load_font(52, bold=True)
        lines = _wrap_text(draw, headline, f_head, max_w)
    line_h = th(draw, "Ag", f_head) + 22
    y = (H - len(lines) * line_h) // 2 - 20
    for line in lines:
        draw.text((TEXT_X, y), line, font=f_head, fill=WHITE)
        y += line_h
    y += 30
    hline(draw, y, x0=TEXT_X, x1=TEXT_X + 300, color=ELECTRIC, width=3)
    draw.text((TEXT_X, y + 30), f"Source: {source}", font=load_font(30), fill=MUTED)
    return img


def scene_outro(date_str):
    img, draw = new_frame()
    _dot_grid(draw)
    f_big = load_font(140, serif=True)
    baiz_w = tw(draw, "Baiz", f_big)
    lx = (W - baiz_w - tw(draw, "ora", f_big)) // 2
    y = 300
    draw.text((lx, y), "Baiz", font=f_big, fill=WHITE)
    draw.text((lx + baiz_w, y), "ora", font=f_big, fill=ELECTRIC)
    y += 200
    centered(draw, y, "US Large-Cap Price & Volume Analytics", load_font(34), MUTED)
    y += 80
    hline(draw, y, x0=W // 2 - 300, x1=W // 2 + 300)
    y += 50
    centered(draw, y, "Subscribe to the Baizora channel", load_font(42, bold=True), WHITE)
    y += 70
    centered(draw, y, "New recap every Wednesday and Friday", load_font(30), MUTED)
    centered(draw, H - 110, "For informational purposes only. Not financial advice.", load_font(22), MUTED)
    centered(draw, H - 70, f"Data as of the {date_str} close", load_font(22, mono=True), DIM)
    return img


# ── Build ───────────────────────────────────────────────────────────────

def build_market_wrap(date_str):
    data = load_session(date_str)
    if data is None:
        return None
    snap = market_snapshot(data)
    if snap["spy"] is None or snap["qqq"] is None or not snap["sp_total"]:
        print("SPY/QQQ or S&P 500 rows missing from latest.json; skipping.")
        return None

    date_obj = datetime.date.fromisoformat(date_str)
    voice, rate = NEWS_TTS_VOICE_EN, WRAP_TTS_RATE

    def beat(img, text):
        return (img, measure_tts_seconds(text, voice, rate), None, text)

    frames = []
    hook = scene_hook(date_obj, date_str)
    frames.append(beat(hook, (
        f"Here's your stock market recap for {_WEEKDAYS[date_obj.weekday()]}, "
        f"{_MONTHS[date_obj.month - 1]} {date_obj.day}. We'll look at how the S&P 500 and the "
        f"Nasdaq-100 closed, which sectors led and lagged, the biggest movers, unusual trading "
        f"volume, and the day's top headlines.")))

    idx_text = (f"The S&P 500 {_move_words(snap['spy'])}, and the Nasdaq-100 "
                f"{_move_words(snap['qqq'], up='gained', down='lost')}. "
                f"{snap['sp_up']} of {snap['sp_total']} S&P 500 stocks closed higher")
    if snap["ndx_total"]:
        idx_text += f", along with {snap['ndx_up']} of {snap['ndx_total']} in the Nasdaq-100"
    frames.append(beat(scene_indexes(snap), idx_text + "."))

    secs = snap["sectors"]
    if len(secs) >= 2 * N_SECTORS_SPOKEN:
        lead = [f"{s}, {_signed(v)}" for s, v, _ in secs[:N_SECTORS_SPOKEN]]
        lag = [f"{s}, {_signed(v)}" for s, v, _ in reversed(secs[-N_SECTORS_SPOKEN:])]
        frames.append(beat(scene_sectors(secs), (
            f"By sector, the leaders were {_join_spoken(lead)}. "
            f"At the bottom were {_join_spoken(lag)}.")))

    if snap["gainers"]:
        parts = [f"{r['Ticker']}, {_signed(r['PriceChange1D'])}" for r in snap["gainers"]]
        frames.append(beat(
            scene_movers(snap["gainers"], "TOP GAINERS", "S&P 500  ·  Nasdaq-100  ·  1-day price change",
                         lambda r: pct_str(r["PriceChange1D"]), lambda r: _pct_color(r["PriceChange1D"])),
            f"Among individual stocks, the top gainers were {_join_spoken(parts)}."))
    if snap["losers"]:
        parts = [f"{r['Ticker']}, {_signed(r['PriceChange1D'])}" for r in snap["losers"]]
        frames.append(beat(
            scene_movers(snap["losers"], "TOP DECLINERS", "S&P 500  ·  Nasdaq-100  ·  1-day price change",
                         lambda r: pct_str(r["PriceChange1D"]), lambda r: _pct_color(r["PriceChange1D"])),
            f"The biggest decliners were {_join_spoken(parts)}."))
    if snap["volume"]:
        parts = [f"{r['Ticker']}, at {r['VolumeVsMA21_1D']:.1f} times" for r in snap["volume"]]
        frames.append(beat(
            scene_movers(snap["volume"], "UNUSUAL VOLUME",
                         "Today's volume vs its 21-day average  ·  1-day price change shown in color",
                         lambda r: f"{r['VolumeVsMA21_1D']:.1f}x", lambda r: _pct_color(r["PriceChange1D"])),
            f"On volume, these stocks traded the most shares compared with their usual 21-day "
            f"average: {_join_spoken(parts)}."))

    stories = []
    try:
        with open(DATA_DIR / "market_news.json", encoding="utf-8") as f:
            items = json.load(f).get("items", [])
        if items:
            stories = curate_stories(items, "en", MAX_STORIES)
    except Exception as e:
        print(f"Headline curation failed ({e}); building the wrap without headlines.")
    for i, s in enumerate(stories):
        narration = s["narration"] if i else f"Now, the day's top headlines. {s['narration']}"
        card = scene_news_card(i + 1, len(stories), s["headline"], s["source"],
                               _trimmed_bg(news_bg_path_for_story(i)))
        frames.append(beat(card, narration))

    frames.append(beat(scene_outro(date_str), _SUBSCRIBE_EN))
    return frames, hook


def main():
    ap = argparse.ArgumentParser(description="Stock Market Recap: Wednesday/Friday stock-market video")
    ap.add_argument("--date", default=None, help="Session date (YYYY-MM-DD); defaults to today")
    ap.add_argument("--output", default="market_wrap.mp4")
    args = ap.parse_args()

    date_str = args.date or datetime.date.today().isoformat()
    built = build_market_wrap(date_str)
    if built is None:
        return  # no output file: the workflow treats that as "not ready / skipped"
    frames, hook = built

    total = sum(f[1] for f in frames)
    print(f"{len(frames)} scenes, {total:.1f}s of narration")
    encode(frames, args.output, xfade_frames=XFADE_FRAMES, tts_rate=WRAP_TTS_RATE, tts_voice=NEWS_TTS_VOICE_EN)
    thumb = str(Path(args.output).with_suffix(".png"))  # upload_youtube.py sends thumbnails as image/png
    hook.save(thumb, optimize=True)
    print("Wrote", args.output, "and", thumb)


if __name__ == "__main__":
    main()
