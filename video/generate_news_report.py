#!/usr/bin/env python3
"""
Baizora Report — daily market-news Short (production).

Reads data/market_news.json (EN) / data/market_news_cn.json (CN), asks
Claude Haiku 4.5 to dedupe near-duplicate headlines, drop generic
listicle/opinion content (not real news events), and paraphrase up to
MAX_STORIES distinct stories into short spoken narration lines — then
renders a vertical (1080x1920) Short: hook -> N story cards -> outro.

Single Wall Street background photo per day (day-rotated across the 4
quadrants split from video/covering/news_background.png), the Baize
mascot (video/baize_mascot.png) with a subtle bob animation standing in
for lip-sync (single static pose, no alternate mouth frames), and a
compact text band so the real photo stays the visual focus.

Requires ANTHROPIC_API_KEY (env var or Firebase-style secret injection —
see scanner.yml). If the Claude API call fails for any reason, the day's
report is skipped (prints a message, writes no output file) rather than
crashing the run — same "skip if not enough content" pattern used by the
other weekday categories in generate_shorts.py.

Usage:
    python generate_news_report.py --lang en --output video/news_report_en.mp4
    python generate_news_report.py --lang cn --output video/news_report_cn.mp4
"""
import argparse
import datetime
import json
import math
import sys
from pathlib import Path

import anthropic
from PIL import Image, ImageDraw

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from generate_video import (  # noqa: E402
    load_font, load_font_cn, tw, th, encode, get_ffmpeg,
    WHITE, MUTED, DIM, GOLD_LIGHT, ELECTRIC, ELEC_BRIGHT, NAVY_LIGHT,
    _wrap_text, _wrap_text_cn,
)
from generate_shorts import (  # noqa: E402
    new_frame_s, centered_s, hline_s, _diamond, scene_ad_short,
    SW, SH, SHORTS_TTS_RATE, SHORTS_TTS_VOICE_CN, _paste_cover,
)

DATA_DIR = SCRIPT_DIR.parent / "data"
COVERING_DIR = SCRIPT_DIR / "covering"
MASCOT_PATH = SCRIPT_DIR / "baize_mascot.png"

MAX_STORIES = 10
MIN_STORIES = 1
TEXT_BAND_H = round(SH * 0.25)

# EN reads at +20% (was +40%, same as the fast-cut weekday Shorts) — this
# narrative news-recap format needs a slower, more natural pace than the
# quick-cut category Shorts. CN pace wasn't flagged, left at SHORTS_TTS_RATE.
NEWS_TTS_VOICE_EN = "en-US-ChristopherNeural"
NEWS_TTS_RATE_EN = "+20%"


def news_tts_params(lang):
    if lang == "en":
        return NEWS_TTS_VOICE_EN, NEWS_TTS_RATE_EN
    return SHORTS_TTS_VOICE_CN, SHORTS_TTS_RATE

_MASCOT_SRC = None


def mascot_src():
    global _MASCOT_SRC
    if _MASCOT_SRC is None:
        _MASCOT_SRC = Image.open(MASCOT_PATH).convert("RGBA")
    return _MASCOT_SRC


def render_mascot(target_h):
    im = mascot_src()
    w, h = im.size
    scale = target_h / h
    return im.resize((round(w * scale), target_h), Image.LANCZOS)


NUM_NEWS_BACKGROUNDS = 10  # News_1..News_10.png — one per story slot, not day-rotated


def news_bg_path_for_story(idx):
    """Each story slot gets its own distinct background photo (News_1.png
    for the first story, News_2.png for the second, ...) so consecutive
    cards look visually different within one video — matches MAX_STORIES
    (10) 1:1. Wraps if a future MAX_STORIES exceeds the photo pool."""
    slot = (idx % NUM_NEWS_BACKGROUNDS) + 1
    return str(COVERING_DIR / f"News_{slot}.png")


def news_bg_path_for_day(date_obj):
    """Used only for the hook scene, which isn't tied to a specific story —
    still day-rotated across the same photo pool for variety."""
    idx = date_obj.toordinal() % NUM_NEWS_BACKGROUNDS + 1
    return str(COVERING_DIR / f"News_{idx}.png")


# ── Duration measurement ────────────────────────────────────────────────
# headlines/narration are dynamic per day, so hold_sec can't be hand-measured
# like the fixed weekday templates. This used to be a word-count regression
# fit against sample edge-tts measurements, but that kept drifting out of
# sync with reality: it needed a full re-fit every time the TTS rate
# changed, and even freshly re-fit it still either overshot (dead air
# before the next scene — the 2026-07-14 "beginning speaks slow, obvious
# pause" report) or undershot (mid-word narration cutoffs) depending on how
# generous the safety buffer was, because word count alone doesn't capture
# per-line variance (punctuation-driven pauses, numbers, proper nouns).
# Now measures the actual synthesized clip directly instead of guessing.

NEWS_TTS_BUFFER = 0.25  # small fixed safety margin over the real measured duration


def measure_tts_seconds(text, voice, rate):
    """Synthesize `text` for real and return its actual duration in seconds
    (+ NEWS_TTS_BUFFER). Same voice/rate must be passed to encode() below so
    the measured value matches what actually gets muxed into the video."""
    import asyncio
    import re
    import subprocess
    import tempfile

    import edge_tts

    with tempfile.TemporaryDirectory() as tmp:
        mp3 = str(Path(tmp) / "measure.mp3")
        asyncio.run(edge_tts.Communicate(text, voice=voice, rate=rate).save(mp3))
        out = subprocess.run([get_ffmpeg(), "-i", mp3], capture_output=True, text=True).stderr
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
        h, mnt, s = m.groups()
        dur = int(h) * 3600 + int(mnt) * 60 + float(s)
    return dur + NEWS_TTS_BUFFER


# ── Claude Haiku 4.5: dedupe + filter + paraphrase ─────────────────────────

_SYSTEM_EN = """You are a financial news editor preparing a short spoken video script.
You will be given today's scraped market news headlines (title + source).

Your job:
1. Group near-duplicate headlines describing the same underlying event (the same story covered by multiple outlets) into a single story.
2. Exclude generic listicle/roundup/opinion content that is not a specific, real news event — e.g. "N things to know before the market opens", "history says this will happen next", vague "is X too big to fail"-style pieces, or pure stock-tip columns.
3. Select up to {max_stories} of the most significant, distinct remaining stories, ordered with the single biggest/most-covered story first.
4. For each story, write:
   - "headline": a short on-screen headline in your own words (rephrase for clarity — do not just copy the raw scraped title verbatim, and strip any trailing " - SourceName" suffix)
   - "narration": one natural spoken sentence narrating the story, paraphrased in your own words (do not read the headline verbatim)
   - "source": the reporting outlet name(s), comma-joined if multiple

Ground everything in the given headlines only — do not invent facts, numbers, or details not present in the input. If fewer than {max_stories} genuine distinct stories exist, return fewer."""

_SYSTEM_CN = """你是一名财经新闻编辑，正在为一个简短的口播视频撰写脚本。
你会收到今天抓取到的市场新闻标题列表（标题+来源，标题为英文）。

任务：
1. 将描述同一事件的相似标题合并为一条新闻（例如多家媒体报道同一件事）。
2. 排除笼统的清单体/评论性内容，这些不是具体的新闻事件（例如"开盘前必读N件事"、"历史表明接下来会发生什么"、"某某是否大到不能倒"这类文章，或纯粹的选股专栏）。
3. 从剩余新闻中选出最多{max_stories}条最重要、彼此不重复的新闻，按重要程度/报道量从高到低排列。
4. 对每一条，用简体中文写出：
   - "headline"：简短的屏幕标题，用自己的话概括（不要逐字翻译原标题，去掉结尾的来源后缀）
   - "narration"：一句自然的中文口播叙述，用自己的话转述（不要逐字朗读标题）
   - "source"：报道来源名称，多个来源用顿号连接

输出内容必须完全基于给定的标题，不能编造原始材料中没有的事实、数字或细节。如果真正独立的新闻不足{max_stories}条，就返回实际数量。"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "narration": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["headline", "narration", "source"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["stories"],
    "additionalProperties": False,
}


def curate_stories(items, lang, max_stories=MAX_STORIES):
    client = anthropic.Anthropic()
    headlines = [{"title": it["title"], "source": it["source"]} for it in items]
    system = (_SYSTEM_EN if lang == "en" else _SYSTEM_CN).format(max_stories=max_stories)

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": json.dumps(headlines, ensure_ascii=False)}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    return data["stories"][:max_stories]


# ── Scene builders ──────────────────────────────────────────────────────

def centered_shadow(draw, y, text, font, fill):
    """Same as centered_s but with a soft dark drop-shadow behind the text —
    the global gradient scrim alone can't guarantee contrast for text that
    sits over a bright sky or building facade (10 different photos rotate
    through here), so low-contrast lines (subtitle, date) get their own
    per-glyph backing instead of relying on a heavier global darken."""
    w = tw(draw, text, font)
    x = (SW - w) // 2
    draw.text((x + 2, y + 2), text, font=font, fill=(6, 13, 31, 220))
    draw.text((x, y), text, font=font, fill=fill)


_FADE_H = TEXT_BAND_H + 120


def _draw_full_bleed_bg(img, draw, bg_path, fade_h=_FADE_H):
    """Photo fills the entire frame — the source photos' aspect ratio
    (~0.563) almost exactly matches the 1080x1920 canvas (0.5625), so this
    crops almost nothing. The earlier design pasted into only a partial-
    height band, which forced a heavy vertical crop on tall monuments/
    buildings (chopping off the Washington Monument's tip, the Capitol
    dome, etc.) — this fixes that. A vertical gradient scrim (dark at top,
    fully clear by fade_h) keeps the headline legible without darkening
    the whole photo."""
    _paste_cover(img, bg_path, (0, 0, SW, SH), valign="center")
    gradient = Image.new("L", (1, SH), 0)
    for y in range(SH):
        alpha = int(190 * (1 - y / fade_h)) if y < fade_h else 0
        gradient.putpixel((0, y), alpha)
    gradient = gradient.resize((SW, SH))
    overlay = Image.new("RGBA", img.size, (6, 13, 31, 0))
    overlay.putalpha(gradient)
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))


def scene_news_card_base(idx, total, headline, source, bg_path, lang="en"):
    img, draw = new_frame_s()
    _draw_full_bleed_bg(img, draw, bg_path)

    eyebrow = "MARKET NEWS" if lang == "en" else "市场新闻"
    f_eyebrow = load_font(26, mono=True) if lang == "en" else load_font_cn(26)
    ew = tw(draw, eyebrow, f_eyebrow)
    badge_w = ew + 90
    ex = (SW - badge_w) // 2 + 46
    ey = 50
    draw.rectangle([ex - 66, ey - 16, ex + ew + 24, ey + 44], fill=NAVY_LIGHT, outline=ELECTRIC, width=2)
    _diamond(draw, ex - 38, ey + 14, 12, ELEC_BRIGHT)
    draw.text((ex, ey), eyebrow, font=f_eyebrow, fill=ELEC_BRIGHT)
    draw.text((SW - 150, ey - 8), f"{idx}/{total}", font=load_font(24, mono=True), fill=DIM)

    if lang == "en":
        f_head = load_font(40, bold=True)
        lines = _wrap_text(draw, headline, f_head, SW - 160)
    else:
        f_head = load_font_cn(38, bold=True)
        lines = _wrap_text_cn(draw, headline, f_head, SW - 160)
    y = 150
    for line in lines:
        centered_shadow(draw, y, line, f_head, WHITE)
        y += th(draw, line, f_head) + 10

    y += 18
    hline_s(draw, y, x0=200, x1=SW - 200)
    y += 26
    dash = "—" if lang == "en" else "——"
    centered_shadow(draw, y, f"{dash} {source}", (load_font(24) if lang == "en" else load_font_cn(22)), MUTED)

    return img


def bob_cycle_frames(base_img, hold_sec, fps=30, cycle_frames=48, amplitude=0.015, bull_h=520):
    """Subtle scale-pulse standing in for lip-sync (mascot is a single
    static pose). Builds only the unique frames in one cycle and repeats
    references to them — memory stays flat regardless of hold_sec."""
    unique = []
    anchor_x, anchor_bottom = SW - 40, SH - 40
    for i in range(cycle_frames):
        phase = (i / cycle_frames) * 2 * math.pi
        scale_factor = 1.0 + amplitude * math.sin(phase)
        h = round(bull_h * scale_factor)
        mascot = render_mascot(h)
        bw, bh = mascot.size
        frame = base_img.copy()
        frame.paste(mascot, (anchor_x - bw, anchor_bottom - bh), mascot)
        unique.append(frame)
    n = int(hold_sec * fps)
    return [unique[i % cycle_frames] for i in range(n)]


def build_news_report(date_str, lang="en"):
    news_path = DATA_DIR / ("market_news.json" if lang == "en" else "market_news_cn.json")
    with open(news_path, encoding="utf-8") as f:
        news = json.load(f)
    items = news.get("items", [])
    if not items:
        print(f"No market news items available for lang={lang}, skipping.")
        return None

    try:
        stories = curate_stories(items, lang, MAX_STORIES)
    except Exception as e:
        print(f"Claude API call failed ({e}), skipping news report for lang={lang}.")
        return None

    if len(stories) < MIN_STORIES:
        print(f"No genuine distinct stories curated for lang={lang}, skipping.")
        return None

    date_obj = datetime.date.fromisoformat(date_str)
    bg_path = news_bg_path_for_day(date_obj)
    tts_voice, tts_rate = news_tts_params(lang)

    def hook_scene():
        img, draw = new_frame_s()
        # Hook's text block runs deeper (title + subtitle + date, to y~680)
        # than the story cards' (headline + source, to y~300) — give it a
        # taller fade so the subtitle/date don't wash out against a bright
        # sky or building facade.
        _draw_full_bleed_bg(img, draw, bg_path, fade_h=780)
        eyebrow = "DAILY MARKET RECAP" if lang == "en" else "每日市场回顾"
        f_eyebrow = load_font(26, mono=True) if lang == "en" else load_font_cn(26)
        ew = tw(draw, eyebrow, f_eyebrow)
        badge_w = ew + 90
        ex = (SW - badge_w) // 2 + 46
        ey = 260
        draw.rectangle([ex - 66, ey - 16, ex + ew + 24, ey + 44], fill=NAVY_LIGHT, outline=ELECTRIC, width=2)
        _diamond(draw, ex - 38, ey + 14, 12, ELEC_BRIGHT)
        draw.text((ex, ey), eyebrow, font=f_eyebrow, fill=ELEC_BRIGHT)
        if lang == "en":
            f_head = load_font(100, serif=True)
            f_sub = load_font(44)
            y = 460
            centered_shadow(draw, y, "MARKET PULSE", f_head, GOLD_LIGHT)
            y += th(draw, "MARKET PULSE", f_head) + 40
            centered_shadow(draw, y, "By Baizora — today's headlines", f_sub, MUTED)
            y += th(draw, "By Baizora — today's headlines", f_sub) + 24
        else:
            f_head = load_font_cn(84, bold=True)
            f_sub = load_font_cn(38)
            y = 460
            centered_shadow(draw, y, "市场脉动", f_head, GOLD_LIGHT)
            y += th(draw, "市场脉动", f_head) + 40
            centered_shadow(draw, y, "贝佐拉 · 今日市场要闻", f_sub, MUTED)
            y += th(draw, "贝佐拉 · 今日市场要闻", f_sub) + 24
        centered_shadow(draw, y, date_str, load_font(32, mono=True), MUTED)
        mascot = render_mascot(820)
        mw, mh = mascot.size
        img.paste(mascot, ((SW - mw) // 2, SH - mh - 30), mascot)
        return img

    _MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                    "August", "September", "October", "November", "December"]
    hook_text = (
        f"Market Pulse by Baizora, {_MONTH_NAMES[date_obj.month - 1]} {date_obj.day}." if lang == "en"
        else f"市场脉动，贝佐拉出品——{date_obj.month}月{date_obj.day}日。"
    )
    hook_dur = measure_tts_seconds(hook_text, tts_voice, tts_rate)

    frames = [(hook_scene(), hook_dur, None, hook_text)]
    total = len(stories)
    for i, story in enumerate(stories):
        headline = story["headline"]
        narration = story["narration"]
        source = story["source"]
        dur = measure_tts_seconds(narration, tts_voice, tts_rate)
        story_bg = news_bg_path_for_story(i)
        base = scene_news_card_base(i + 1, total, headline, source, story_bg, lang=lang)
        clip = bob_cycle_frames(base, dur)
        frames.append((clip, dur, None, narration))

    outro_text = (
        "Get the full daily briefing, every headline, free at baizora dot com." if lang == "en"
        else "获取完整每日简报和全部要闻，前往baizora点com。"
    )
    outro_dur = measure_tts_seconds(outro_text, tts_voice, tts_rate)
    frames.append((scene_ad_short(date_str, lang=lang), outro_dur, None, outro_text))

    return frames


def main():
    ap = argparse.ArgumentParser(description="Baizora Report — daily market-news Short")
    ap.add_argument("--lang", default="en", choices=["en", "cn"])
    ap.add_argument("--output", default=None)
    ap.add_argument("--date", default=None, help="Override date (YYYY-MM-DD); defaults to today")
    args = ap.parse_args()

    date_str = args.date or datetime.date.today().isoformat()
    output = args.output or f"news_report_{args.lang}.mp4"

    frames = build_news_report(date_str, lang=args.lang)
    if frames is None:
        return  # skip — no output file written, matches other categories' skip pattern

    tts_voice, tts_rate = news_tts_params(args.lang)
    encode(frames, output, xfade_frames=3, tts_rate=tts_rate, tts_voice=tts_voice)
    print("Wrote", output)


if __name__ == "__main__":
    main()
