#!/usr/bin/env python3
"""
Stock Profile: daily general-information Short about one company (2026-10-21).

One S&P 500 / Nasdaq-100 company per calendar day, EN only, vertical 1080x1920:
  1. Hook      ticker, company name, sector, index membership
  2. About     what the company does (first sentences of its Wikipedia summary,
               data/company_descriptions.json; attributed on screen)
  3. Numbers   last close, market cap, P/E vs sector average, EPS
  4. Chart     1-year daily candlesticks + 1-year change and range
  5. Outro     brand card + subscribe line (info-only, no website mention)

Neutral facts only, no opinion or "should you buy" framing. Everything comes
from committed data files and is narrated by template; no LLM involved.

Pick: stocks with a description, sorted by market cap (largest first), and
walked one per day from ROTATION_START, so the same date always gets the same
company (retries never switch stocks) and the full list cycles in ~17 months.

Usage:
    python generate_stock_profile.py --date 2026-10-22 --output video/stock_profile.mp4
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from generate_video import (  # noqa: E402
    load_font, tw, th, encode, pct_str,
    WHITE, MUTED, DIM, GOLD_LIGHT, BRIGHT_GREEN, BRIGHT_RED,
)
from generate_shorts import (  # noqa: E402
    new_frame_s, centered_s, hline_s, dot_grid_s, scene_ad_short, SW, SH,
    _draw_candles_with_volume, _compute_range_extremes, _wrap_text,
)
from generate_thumbnail import load_headline_font  # noqa: E402
from generate_news_report import measure_tts_seconds, news_tts_params  # noqa: E402
from generate_market_wrap import _eyebrow  # noqa: E402

DATA_DIR = SCRIPT_DIR.parent / "data"
ROTATION_START = datetime.date(2026, 10, 22)  # day 0 = largest company by market cap

_SUBSCRIBE_EN = "We profile a different S&P 500 or Nasdaq-100 company every day. Subscribe to the Baizora channel for more."


# ── Data ────────────────────────────────────────────────────────────────

def _load(name):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _last_finished_session(max_commits=20):
    """Most recent committed data/latest.json without the midday flag (needs the
    workflow's fetch-depth: 0 checkout)."""
    repo = DATA_DIR.parent
    try:
        shas = subprocess.run(
            ["git", "log", f"-{max_commits}", "--format=%H", "--", "data/latest.json"],
            cwd=repo, capture_output=True, text=True, check=True).stdout.split()
        for sha in shas:
            blob = subprocess.run(["git", "show", f"{sha}:data/latest.json"],
                                  cwd=repo, capture_output=True, check=True).stdout
            d = json.loads(blob.decode("utf-8"))
            if not d.get("midday"):
                return d
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f"git fallback failed: {e}")
    return None


_NAME_STOP = {"inc", "corp", "corporation", "company", "co", "the", "group", "holdings", "ltd",
              "plc", "class", "and", "of", "international", "technologies", "nv", "sa", "se",
              "limited", "common", "stock", "de", "uk"}


def _name_tokens(s):
    s = (s or "").lower().replace("'", "").replace("’", "")
    return {w for w in re.findall(r"[a-z0-9]+", s) if w not in _NAME_STOP and len(w) > 1}


def description_matches(row, desc):
    """Some Wikipedia matches in company_descriptions.json are simply wrong
    (2026-10-21: IBM -> Commodore International, ARM -> Standard Life plc,
    AEP/VYLR -> "Company"). Require the SEC company name to share a word with
    the article's name or opening, so a profile never narrates the wrong firm."""
    a = _name_tokens(desc.get("name")) | _name_tokens(desc.get("description", "")[:150])
    return bool(a & _name_tokens(row.get("CompanyName")))


def pick_stock(date_obj, data, descriptions):
    stale = set(data.get("staleTickers") or [])
    universe = [r for r in data.get("data", [])
                if (r.get("InSP500") or r.get("InNASDAQ100"))
                and r.get("Ticker") not in stale
                and r.get("Price") and r.get("MarketCap")
                and (descriptions.get(r["Ticker"]) or {}).get("description")
                and description_matches(r, descriptions[r["Ticker"]])]
    universe.sort(key=lambda r: (-r["MarketCap"], r["Ticker"]))
    # One profile per company: GOOGL/GOOG, FOXA/FOX etc. share an article.
    seen, deduped = set(), []
    for r in universe:
        key = descriptions[r["Ticker"]].get("wiki_url") or descriptions[r["Ticker"]].get("name")
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    universe = deduped
    if not universe:
        return None
    return universe[(date_obj - ROTATION_START).days % len(universe)]


def short_description(text, min_len=170, max_len=420):
    """Leading whole sentences, at least min_len chars where possible, never past max_len."""
    sentences = re.split(r"(?<=[a-z0-9)\]]\.)\s+(?=[A-Z])", text.strip())
    out = ""
    for s in sentences:
        trial = f"{out} {s}".strip()
        if out and len(trial) > max_len:
            break
        out = trial
        if len(out) >= min_len:
            break
    if len(out) > max_len:
        out = out[:max_len].rsplit(" ", 1)[0].rstrip(",;") + "..."
    return out


def fmt_cap(billions):
    if billions >= 1000:
        return f"${billions / 1000:.2f}T", f"{billions / 1000:.1f} trillion dollars"
    return f"${billions:,.1f}B", f"{billions:,.0f} billion dollars"


def index_label(r):
    if r.get("InSP500") and r.get("InNASDAQ100"):
        return "S&P 500  ·  Nasdaq-100"
    return "S&P 500" if r.get("InSP500") else "Nasdaq-100"


# ── Scenes ──────────────────────────────────────────────────────────────

def scene_hook(r, name, date_str):
    img, draw = new_frame_s()
    dot_grid_s(draw)
    _eyebrow(draw, "STOCK MARKET", 380)
    f_tkr = load_headline_font(220)
    y = 520
    centered_s(draw, y, r["Ticker"], f_tkr, GOLD_LIGHT)
    y += draw.textbbox((0, 0), r["Ticker"], font=f_tkr)[3] + 50
    f_name = load_font(54, bold=True)
    for line in _wrap_text(draw, name, f_name, SW - 160, "en")[:2]:
        centered_s(draw, y, line, f_name, WHITE)
        y += th(draw, line, f_name) + 14
    y += 30
    centered_s(draw, y, r.get("Sector") or "", load_font(36), MUTED)
    y += 70
    centered_s(draw, y, index_label(r), load_font(30, mono=True), MUTED)
    centered_s(draw, SH - 220, f"Data as of {date_str}", load_font(22, mono=True), DIM)
    return img


def scene_about(r, about):
    img, draw = new_frame_s()
    dot_grid_s(draw)
    _eyebrow(draw, f"ABOUT {r['Ticker']}", 200)
    f = load_font(46)
    lines = _wrap_text(draw, about, f, SW - 180, "en")
    line_h = th(draw, "Ag", f) + 22
    y = max(380, (SH - len(lines) * line_h) // 2 - 80)
    for line in lines:
        draw.text((90, y), line, font=f, fill=WHITE)
        y += line_h
    y += 40
    draw.text((90, y), "Source: Wikipedia", font=load_font(24, mono=True), fill=DIM)
    return img


def scene_numbers(r, stats):
    img, draw = new_frame_s()
    dot_grid_s(draw)
    _eyebrow(draw, "BY THE NUMBERS", 160)
    f_label = load_font(30, mono=True)
    f_val = load_headline_font(110)
    f_note = load_font(28)
    y = 330
    for label, value, note in stats:
        hline_s(draw, y, x0=90, x1=SW - 90)
        draw.text((90, y + 40), label, font=f_label, fill=MUTED)
        draw.text((SW - 90 - tw(draw, value, f_val), y + 20), value, font=f_val, fill=WHITE)
        if note:
            draw.text((90, y + 92), note, font=f_note, fill=DIM)
        y += 260
    hline_s(draw, y, x0=90, x1=SW - 90)
    return img


def scene_chart(r, chg, range_ext):
    img, draw = new_frame_s()
    dot_grid_s(draw)
    _eyebrow(draw, "THE PAST YEAR", 120)
    region = (110, 260, SW - 110, 1280)
    _draw_candles_with_volume(img, draw, r["Ticker"], region, range_ext=range_ext)
    if chg is not None:
        f_pct = load_headline_font(140)
        txt = pct_str(chg)
        centered_s(draw, 1340, txt, f_pct, BRIGHT_GREEN if chg >= 0 else BRIGHT_RED)
        bottom = 1340 + draw.textbbox((0, 0), txt, font=f_pct)[3]
        centered_s(draw, bottom + 30, "1-YEAR PRICE CHANGE", load_font(26, mono=True), DIM)
    return img


# ── Build ───────────────────────────────────────────────────────────────

def build_stock_profile(date_str):
    data = _load("latest.json")
    if data.get("midday"):
        # A manual midday scan leaves a partial-day latest.json in place until the
        # evening scan, and GitHub can delay this workflow's crons by hours into that
        # window (both 2026-10-22 runs skipped this way). Profile the last finished
        # session from git history instead.
        data = _last_finished_session()
        if data is None:
            print("latest.json is a midday snapshot and no finished session was found in git; skipping.")
            return None
        print(f"latest.json is a midday snapshot; using the finished {data.get('date')} session from git.")
    descriptions = _load("company_descriptions.json")
    try:
        overrides = _load("company_description_overrides.json")
    except FileNotFoundError:
        overrides = {}

    r = pick_stock(datetime.date.fromisoformat(date_str), data, descriptions)
    if r is None:
        print("No eligible stocks; skipping.")
        return None
    t = r["Ticker"]
    desc = descriptions[t]
    name = overrides.get(t) or desc.get("name") or (r.get("CompanyName") or t).title()
    about = short_description(desc["description"])
    data_date = data.get("date", date_str)
    print(f"Stock Profile {date_str}: {t} ({name})")

    voice, rate = news_tts_params("en")

    def beat(img, text):
        return (img, measure_tts_seconds(text, voice, rate), None, text)

    frames = [beat(scene_hook(r, name, data_date),
                   f"Today's stock profile: {name}, ticker {t}, in the {r.get('Sector') or 'stock'} sector.")]
    frames.append(beat(scene_about(r, about), about))

    cap_txt, cap_spoken = fmt_cap(r["MarketCap"])
    price = r["Price"]
    stats = [("LAST CLOSE", f"${price:,.2f}", None), ("MARKET CAP", cap_txt, None)]
    spoken = f"{t} last closed at ${price:,.2f}, for a market value of about {cap_spoken}."
    pe, sector_pe, eps = r.get("PE"), r.get("SectorAvgPE"), r.get("EPS")
    if pe and pe > 0:
        note = f"Sector average: {sector_pe:.1f}" if sector_pe else None
        stats.append(("P/E RATIO", f"{pe:.1f}", note))
        spoken += f" Its price to earnings ratio is {pe:.1f}"
        spoken += f", compared with a sector average of {sector_pe:.1f}." if sector_pe else "."
    if eps is not None:
        stats.append(("EPS (TTM)", f"${eps:,.2f}" if eps >= 0 else f"-${abs(eps):,.2f}", None))
    frames.append(beat(scene_numbers(r, stats), spoken))

    chg = r.get("1YPriceChange")
    range_ext = _compute_range_extremes(t)
    if chg is not None or range_ext:
        line = ""
        if chg is not None:
            line = f"Over the past year, {t} is {'up' if chg >= 0 else 'down'} {abs(chg):.0f} percent."
        if range_ext:
            line += (f" Its lowest close was {abs(range_ext['lo_pct']):.0f} percent "
                     f"{'below' if range_ext['lo_pct'] < 0 else 'above'} its price a year ago, "
                     f"and its highest was {abs(range_ext['hi_pct']):.0f} percent "
                     f"{'above' if range_ext['hi_pct'] >= 0 else 'below'}.")
        frames.append(beat(scene_chart(r, chg, range_ext), line.strip()))

    frames.append(beat(scene_ad_short(data_date, lang="en"), _SUBSCRIBE_EN))
    return frames, t, name, data_date


def main():
    ap = argparse.ArgumentParser(description="Stock Profile: daily company Short")
    ap.add_argument("--date", default=None, help="Profile date (YYYY-MM-DD); picks the stock; defaults to today")
    ap.add_argument("--output", default="stock_profile.mp4")
    args = ap.parse_args()

    date_str = args.date or datetime.date.today().isoformat()
    built = build_stock_profile(date_str)
    if built is None:
        return
    frames, ticker, name, data_date = built
    voice, rate = news_tts_params("en")
    encode(frames, args.output, xfade_frames=3, tts_rate=rate, tts_voice=voice)
    # The workflow reads this sidecar for the YouTube title.
    Path(args.output).with_suffix(".json").write_text(
        json.dumps({"ticker": ticker, "name": name, "data_date": data_date}), encoding="utf-8")
    print("Wrote", args.output)


if __name__ == "__main__":
    main()
