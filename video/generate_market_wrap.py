#!/usr/bin/env python3
"""
Market Wrap: general stock-market Short, every Wednesday and Friday (2026-10-21).

Vertical (1080x1920) recap of the day's session, EN only:
  1. Hook        "MARKET WRAP", weekday eyebrow, date
  2. Indexes     S&P 500 (via SPY) + Nasdaq-100 (via QQQ) day change, S&P 500 breadth
  3. Gainers     top 5 S&P 500 / Nasdaq-100 stocks by 1-day price change
  4. Decliners   bottom 5, same universe
  5. Headlines   up to MAX_STORIES of the day's market news, curated by Claude Haiku
                 (same curate_stories() as the Market Pulse news video)
  6. Outro       brand card + subscribe line (info-only, no website mention)

All numbers come straight from data/latest.json and are narrated by template,
never by the LLM, so nothing numeric can be hallucinated. The LLM only touches
the headline section; if that call fails the video still ships without it.

Skips (writes no output file) unless data/latest.json holds the requested
date's finished session (not the midday snapshot) — on a market holiday or a
late scan the workflow's retry cron tries again later.

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
    load_font, tw, th, encode, pct_str,
    WHITE, MUTED, DIM, GOLD_LIGHT, ELECTRIC, ELEC_BRIGHT, NAVY_LIGHT,
    BRIGHT_GREEN, BRIGHT_RED,
)
from generate_shorts import (  # noqa: E402
    new_frame_s, centered_s, hline_s, dot_grid_s, _diamond, scene_ad_short, SW,
)
from generate_thumbnail import load_headline_font  # noqa: E402
from generate_news_report import (  # noqa: E402
    curate_stories, measure_tts_seconds, news_tts_params, centered_shadow,
    _draw_full_bleed_bg, scene_news_card_base, news_bg_path_for_story,
    news_bg_path_for_day,
)

DATA_DIR = SCRIPT_DIR.parent / "data"

MAX_STORIES = 5
N_MOVERS = 5        # rows shown per movers scene
N_MOVERS_SPOKEN = 3  # rows narrated per movers scene (keeps the Short tight)

_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_SUBSCRIBE_EN = "We wrap up the market every Wednesday and Friday. Subscribe to the Baizora channel for more."


_TRIM_DIR = Path(tempfile.mkdtemp(prefix="market_wrap_bg_"))


def _trimmed_bg(path, border=8):
    """Some News_*.png photos carry a thin white strip along an edge, which
    shows once scaled to full-bleed. Crop a few px off every side first."""
    out = _TRIM_DIR / Path(path).name
    if not out.exists():
        im = Image.open(path)
        w, h = im.size
        im.crop((border, border, w - border, h - border)).save(out)
    return str(out)


def _eyebrow(draw, text, y):
    f = load_font(26, mono=True)
    ew = tw(draw, text, f)
    ex = (SW - (ew + 90)) // 2 + 46
    draw.rectangle([ex - 66, y - 16, ex + ew + 24, y + 44], fill=NAVY_LIGHT, outline=ELECTRIC, width=2)
    _diamond(draw, ex - 38, y + 14, 12, ELEC_BRIGHT)
    draw.text((ex, y), text, font=f, fill=ELEC_BRIGHT)


def _move_words(v, up="rose", down="fell"):
    """'rose 0.42 percent' / 'fell 1.10 percent' / 'was flat'."""
    if v is None or abs(v) < 0.005:
        return "was flat"
    return f"{up if v > 0 else down} {abs(v):.2f} percent"


def _pct_color(v):
    return BRIGHT_GREEN if (v or 0) >= 0 else BRIGHT_RED


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
    ranked = sorted(stocks, key=lambda r: r["PriceChange1D"], reverse=True)
    spy, qqq = by_ticker.get("SPY"), by_ticker.get("QQQ")
    return {
        "spy": spy.get("PriceChange1D") if spy else None,
        "qqq": qqq.get("PriceChange1D") if qqq else None,
        "sp_up": sum(1 for r in sp if r["PriceChange1D"] > 0),
        "sp_down": sum(1 for r in sp if r["PriceChange1D"] < 0),
        "sp_total": len(sp),
        "gainers": [r for r in ranked if r["PriceChange1D"] > 0][:N_MOVERS],
        "losers": [r for r in reversed(ranked) if r["PriceChange1D"] < 0][:N_MOVERS],
    }


# ── Scenes ──────────────────────────────────────────────────────────────

def scene_hook(date_obj, date_str):
    img, draw = new_frame_s()
    _draw_full_bleed_bg(img, draw, _trimmed_bg(news_bg_path_for_day(date_obj)), fade_h=1100)
    _eyebrow(draw, f"{_WEEKDAYS[date_obj.weekday()].upper()} MARKET WRAP", 300)
    f_head = load_headline_font(170)
    y = 470
    centered_shadow(draw, y, "MARKET", f_head, WHITE)
    y += draw.textbbox((0, 0), "MARKET", font=f_head)[3] + 20
    centered_shadow(draw, y, "WRAP", f_head, GOLD_LIGHT)
    y += draw.textbbox((0, 0), "WRAP", font=f_head)[3] + 60
    f_sub = load_font(44)
    centered_shadow(draw, y, "S&P 500  ·  Nasdaq-100", f_sub, WHITE)
    y += th(draw, "S&P 500", f_sub) + 30
    centered_shadow(draw, y, date_str, load_font(34, mono=True), MUTED)
    return img


def scene_indexes(snap):
    img, draw = new_frame_s()
    dot_grid_s(draw)
    _eyebrow(draw, "THE MARKET TODAY", 120)

    f_label = load_font(46, bold=True)
    f_pct = load_headline_font(170)
    f_via = load_font(24, mono=True)
    y = 380
    for label, via, v in (("S&P 500", "via SPY", snap["spy"]), ("NASDAQ-100", "via QQQ", snap["qqq"])):
        centered_s(draw, y, label, f_label, MUTED)
        y += th(draw, label, f_label) + 30
        txt = pct_str(v) if v is not None else "n/a"
        centered_s(draw, y, txt, f_pct, _pct_color(v))
        y += draw.textbbox((0, 0), txt, font=f_pct)[3] + 24
        centered_s(draw, y, via, f_via, DIM)
        y += 130

    hline_s(draw, y - 40, x0=200, x1=SW - 200)
    y += 30
    centered_s(draw, y, "S&P 500 BREADTH", load_font(28, mono=True), MUTED)
    y += 70
    up, down, total = snap["sp_up"], snap["sp_down"], max(snap["sp_total"], 1)
    x0, x1, bar_h = 120, SW - 120, 44
    split = x0 + round((x1 - x0) * up / total)
    draw.rectangle([x0, y, x1, y + bar_h], fill=NAVY_LIGHT)
    if up:
        draw.rectangle([x0, y, split, y + bar_h], fill=BRIGHT_GREEN)
    down_x = x1 - round((x1 - x0) * down / total)
    if down:
        draw.rectangle([down_x, y, x1, y + bar_h], fill=BRIGHT_RED)
    y += bar_h + 30
    f_cnt = load_font(40, bold=True)
    draw.text((x0, y), f"{up} up", font=f_cnt, fill=BRIGHT_GREEN)
    dtxt = f"{down} down"
    draw.text((x1 - tw(draw, dtxt, f_cnt), y), dtxt, font=f_cnt, fill=BRIGHT_RED)
    return img


def scene_movers(rows, title, date_str):
    img, draw = new_frame_s()
    dot_grid_s(draw)
    _eyebrow(draw, title, 120)
    centered_s(draw, 220, "S&P 500  ·  Nasdaq-100  ·  1-day change", load_font(28), MUTED)

    f_rank = load_font(30, mono=True)
    f_tkr = load_headline_font(78)
    f_name = load_font(28)
    f_pct = load_headline_font(78)
    y = 340
    row_h = 250
    for i, r in enumerate(rows):
        hline_s(draw, y, x0=90, x1=SW - 90)
        top = y + 40
        draw.text((90, top + 20), f"{i + 1:02d}", font=f_rank, fill=DIM)
        draw.text((170, top), r.get("Ticker", ""), font=f_tkr, fill=WHITE)
        name = (r.get("CompanyName") or "").title()
        if len(name) > 32:
            name = name[:29] + "..."
        draw.text((172, top + 112), name, font=f_name, fill=MUTED)
        v = r["PriceChange1D"]
        ptxt = pct_str(v)
        draw.text((SW - 90 - tw(draw, ptxt, f_pct), top), ptxt, font=f_pct, fill=_pct_color(v))
        y += row_h
    hline_s(draw, y, x0=90, x1=SW - 90)
    return img


# ── Build ───────────────────────────────────────────────────────────────

def _movers_line(rows, intro, verb):
    def num(v):
        return f"{abs(v):.1f}".removesuffix(".0")  # "9.0" reads as "nine point zero"
    parts = [f"{r['Ticker']}, {verb} {num(r['PriceChange1D'])} percent" for r in rows[:N_MOVERS_SPOKEN]]
    if len(parts) > 1:
        parts[-1] = "and " + parts[-1]
    return f"{intro}: " + ", ".join(parts) + "."


def build_market_wrap(date_str):
    data = load_session(date_str)
    if data is None:
        return None
    snap = market_snapshot(data)
    if snap["spy"] is None or snap["qqq"] is None or not snap["sp_total"]:
        print("SPY/QQQ or S&P 500 rows missing from latest.json; skipping.")
        return None

    date_obj = datetime.date.fromisoformat(date_str)
    voice, rate = news_tts_params("en")

    def beat(img, text):
        return (img, measure_tts_seconds(text, voice, rate), None, text)

    frames = []
    hook_text = f"Market Wrap for {_WEEKDAYS[date_obj.weekday()]}, {_MONTHS[date_obj.month - 1]} {date_obj.day}."
    frames.append(beat(scene_hook(date_obj, date_str), hook_text))

    idx_text = (f"The S&P 500 {_move_words(snap['spy'])}, and the Nasdaq-100 "
                f"{_move_words(snap['qqq'], up='gained', down='lost')}. "
                f"{snap['sp_up']} of {snap['sp_total']} S&P 500 stocks closed higher.")
    frames.append(beat(scene_indexes(snap), idx_text))

    if snap["gainers"]:
        frames.append(beat(scene_movers(snap["gainers"], "TOP GAINERS", date_str),
                           _movers_line(snap["gainers"], "The top gainers", "up")))
    if snap["losers"]:
        frames.append(beat(scene_movers(snap["losers"], "TOP DECLINERS", date_str),
                           _movers_line(snap["losers"], "The biggest decliners", "down")))

    stories = []
    try:
        with open(DATA_DIR / "market_news.json", encoding="utf-8") as f:
            items = json.load(f).get("items", [])
        if items:
            stories = curate_stories(items, "en", MAX_STORIES)
    except Exception as e:
        print(f"Headline curation failed ({e}); building the wrap without headlines.")
    for i, s in enumerate(stories):
        narration = s["narration"] if i else f"In the news. {s['narration']}"
        card = scene_news_card_base(i + 1, len(stories), s["headline"], s["source"],
                                    _trimmed_bg(news_bg_path_for_story(i)), lang="en")
        frames.append(beat(card, narration))

    frames.append(beat(scene_ad_short(date_str, lang="en"), _SUBSCRIBE_EN))
    return frames


def main():
    ap = argparse.ArgumentParser(description="Market Wrap: Wednesday/Friday stock-market Short")
    ap.add_argument("--date", default=None, help="Session date (YYYY-MM-DD); defaults to today")
    ap.add_argument("--output", default="market_wrap.mp4")
    args = ap.parse_args()

    date_str = args.date or datetime.date.today().isoformat()
    frames = build_market_wrap(date_str)
    if frames is None:
        return  # no output file: the workflow treats that as "not ready / skipped"

    voice, rate = news_tts_params("en")
    encode(frames, args.output, xfade_frames=3, tts_rate=rate, tts_voice=voice)
    print("Wrote", args.output)


if __name__ == "__main__":
    main()
