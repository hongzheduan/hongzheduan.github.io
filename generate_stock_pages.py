#!/usr/bin/env python3
"""Generate individual stock pages for featured S&P 500 / Nasdaq-100 tickers."""

import json
from datetime import datetime
from pathlib import Path

ROOT_DIR     = Path(__file__).parent
DATA_FILE    = ROOT_DIR / "data" / "latest.json"
CANDLES_FILE = ROOT_DIR / "data" / "candles.json"
OUTPUT_DIR   = ROOT_DIR / "stocks"

TOP10_NASDAQ = ["NVDA", "GOOGL", "AAPL", "MSFT", "AMZN", "AVGO", "TSLA", "META", "WMT", "MU"]

FEATURED_TICKERS = [
    "NVDA", "TSLA", "AAPL", "MSFT", "META", "GOOGL", "AMZN",
    "WMT", "MU", "NFLX", "AMD", "AVGO", "ORCL", "CRM", "NOW", "PLTR",
    "UBER", "ABNB", "COIN", "PANW", "CRWD", "SMCI",
    "VOO", "QQQ",
]

# ETFs don't have InSP500/InNASDAQ100 set (they track an index, they aren't a
# constituent of one) and their fundamentals are blank by design (see
# scanner_tiingo.py's ETF_TICKERS short-circuit) — this tells generate_summary()/
# generate_page() which index each one tracks, for the badge/summary text, since
# there's no other field to derive it from.
ETF_TRACKS = {
    "VOO": "S&P 500", "SPY": "S&P 500", "IVV": "S&P 500", "SPLG": "S&P 500",
    "QQQ": "Nasdaq-100", "QQQM": "Nasdaq-100",
}

# ---------------------------------------------------------------------------
# Chart + IEX script template (regular string — no f-string escaping needed).
# Placeholders: __DATES__, __OHLCV__, __TICKER__
# ---------------------------------------------------------------------------
_SCRIPT_TEMPLATE = r"""
<script>
(function() {
  /* ---- Candlestick chart ---- */
  var DATES = __DATES__;
  var OHLCV  = __OHLCV__;

  function renderChart() {
    var canvas = document.getElementById('stockChart');
    if (!canvas || !OHLCV.length) return;
    var dpr  = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    if (!rect.width) return;
    canvas.width  = Math.round(rect.width  * dpr);
    canvas.height = Math.round(rect.height * dpr);
    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    var W = rect.width, H = rect.height;
    var hasVol = OHLCV.some(function(c) { return c[4] > 0; });
    var volH   = hasVol ? Math.round(H * 0.22) : 0;
    var gap    = hasVol ? 6 : 0;
    var pad    = { top:20, right:16, bottom:28, left:58 };
    var priceH = H - pad.top - pad.bottom - volH - gap;
    var n      = OHLCV.length;
    var slotW  = (W - pad.left - pad.right) / n;
    var cndW   = Math.max(1, slotW * 0.65);
    function toX(i) { return pad.left + i * slotW + (slotW - cndW) / 2; }
    var minP = Infinity, maxP = -Infinity;
    OHLCV.forEach(function(c) { if(c[1]>maxP) maxP=c[1]; if(c[2]<minP) minP=c[2]; });
    var buf = (maxP - minP) * 0.05 || 1;
    var lo = minP - buf, hi = maxP + buf;
    function toY(p) { return pad.top + priceH * (1 - (p - lo) / (hi - lo)); }
    ctx.clearRect(0, 0, W, H);
    /* grid + price labels */
    ctx.font = "11px 'DM Mono',monospace";
    ctx.textAlign = "right";
    for (var gi = 0; gi <= 4; gi++) {
      var p = lo + (hi - lo) * (gi / 4);
      var y = toY(p);
      ctx.strokeStyle = "rgba(255,255,255,0.06)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(W - pad.right, y); ctx.stroke();
      ctx.fillStyle = "#64748b";
      ctx.fillText(p >= 1000 ? p.toFixed(0) : p.toFixed(2), pad.left - 5, y + 4);
    }
    /* latest date top-right */
    if (DATES.length) {
      var ld = new Date(DATES[DATES.length - 1] + 'T12:00:00');
      ctx.font = "10px 'DM Mono',monospace"; ctx.fillStyle = "#475569"; ctx.textAlign = "right";
      ctx.fillText(ld.toLocaleDateString("en-US", {month:"short",day:"numeric",year:"numeric"}), W - pad.right, pad.top - 4);
    }
    /* x-axis date labels */
    ctx.font = "11px 'DM Mono',monospace"; ctx.textAlign = "center";
    var lastMo = -1, lastYr = -1, moCount = 0;
    DATES.forEach(function(d, i) {
      var dt = new Date(d + 'T12:00:00');
      var mo = dt.getMonth(), yr = dt.getFullYear();
      if (n < 100) {
        if (i % Math.round(n / 6) !== 0) return;
        ctx.fillStyle = "#64748b";
        ctx.fillText(dt.toLocaleDateString("en-US", {month:"short",day:"numeric"}), toX(i) + cndW / 2, H - 8);
      } else {
        if (mo === lastMo) return;
        lastMo = mo; moCount++;
        if (n >= 200 && moCount % 2 === 0) return;
        var moName = dt.toLocaleDateString("en-US", {month:"short"});
        var label  = yr !== lastYr ? moName + " '" + String(yr).slice(-2) : moName;
        lastYr = yr;
        ctx.fillStyle = "#64748b";
        ctx.fillText(label, toX(i) + cndW / 2, H - 8);
      }
    });
    /* candlesticks */
    OHLCV.forEach(function(c, i) {
      var o = c[0], h = c[1], l = c[2], cl = c[3];
      var green = cl >= o;
      var x = toX(i), mid = x + cndW / 2;
      ctx.strokeStyle = green ? "#22c55e" : "#ef4444";
      ctx.fillStyle   = green ? "rgba(34,197,94,0.75)" : "rgba(239,68,68,0.75)";
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(mid, toY(h)); ctx.lineTo(mid, toY(l)); ctx.stroke();
      var bTop = toY(Math.max(o, cl));
      var bH   = Math.max(1, toY(Math.min(o, cl)) - bTop);
      ctx.fillRect(x, bTop, cndW, bH);
      ctx.strokeRect(x, bTop, cndW, bH);
    });
    /* volume panel */
    if (hasVol) {
      var volTop = pad.top + priceH + gap;
      var maxVol = Math.max.apply(null, OHLCV.map(function(c) { return c[4] || 0; }));
      ctx.strokeStyle = "rgba(255,255,255,0.06)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pad.left, volTop); ctx.lineTo(W - pad.right, volTop); ctx.stroke();
      ctx.fillStyle = "#475569"; ctx.font = "9px 'DM Mono',monospace"; ctx.textAlign = "right";
      ctx.fillText("VOL", pad.left - 5, volTop + 9);
      OHLCV.forEach(function(c, i) {
        if (!c[4]) return;
        var green = c[3] >= c[0];
        var bH = Math.round((c[4] / maxVol) * (volH - 4));
        ctx.fillStyle = green ? "rgba(34,197,94,0.45)" : "rgba(239,68,68,0.45)";
        ctx.fillRect(toX(i), volTop + (volH - 4) - bH, cndW, bH);
      });
    }
  }

  renderChart();
  var _rt;
  window.addEventListener('resize', function() { clearTimeout(_rt); _rt = setTimeout(renderChart, 120); });

  /* ---- Live IEX prices (market hours only) ---- */
  var TICKER = "__TICKER__";

  // Fetch latest candles.json — keeps chart current without page regeneration
  (function() {
    fetch('../data/candles.json').then(function(r) { return r.json(); }).then(function(cj) {
      var d  = (cj.data || {})[TICKER];
      var ds = cj.dates || [];
      if (!d || !d.length || ds.length !== d.length) return;
      DATES = ds; OHLCV = d;
      renderChart();
      var ld = new Date(ds[ds.length - 1] + 'T12:00:00');
      var fmt = ld.toLocaleDateString('en-US', {month: 'long', day: 'numeric', year: 'numeric'});
      var sd = document.querySelector('.scan-date');
      if (sd) sd.textContent = 'Data as of ' + fmt + ' · Updated daily after market close';
      var ct = document.getElementById('chartSectionTitle');
      if (ct) ct.textContent = '1-Year Candlestick & Volume  ·  Scan date: ' + ds[ds.length - 1];
      var sb = document.querySelector('.summary-box');
      if (sb) sb.innerHTML = sb.innerHTML.replace(/today \([^)]+\)/, 'today (' + fmt + ')');
    }).catch(function() {});
  })();

  var IEX    = "https://us-central1-baizora.cloudfunctions.net/api/iex-quotes";

  function isMarketOpen() {
    try {
      var et = new Date(new Date().toLocaleString("en-US", {timeZone:"America/New_York"}));
      var d = et.getDay();
      if (d === 0 || d === 6) return false;
      var m = et.getHours() * 60 + et.getMinutes();
      return m >= 570 && m < 960;
    } catch(e) { return false; }
  }

  function refresh() {
    fetch(IEX).then(function(r) { return r.json(); }).then(function(q) {
      if (!q || !Object.keys(q).length) return;
      var d = q[TICKER];
      if (d && d.last != null) {
        var priceEl  = document.querySelector(".price");
        var changeEl = document.querySelector(".change");
        var dateEl   = document.querySelector(".scan-date");
        if (priceEl)  priceEl.textContent = "$" + d.last.toFixed(2);
        if (changeEl && d.chgPct != null) {
          var pc = d.chgPct;
          changeEl.textContent = (pc >= 0 ? "+" : "") + pc.toFixed(2) + "%";
          changeEl.style.color = pc >= 0 ? "#22c55e" : "#ef4444";
        }
        if (dateEl) {
          var t = new Date().toLocaleTimeString("en-US", {hour:"numeric",minute:"2-digit",timeZone:"America/New_York"});
          dateEl.textContent = "Live price · As of " + t + " ET";
        }
      }
      document.querySelectorAll(".peer-card").forEach(function(card) {
        var tkEl = card.querySelector(".peer-ticker");
        if (!tkEl) return;
        var t  = tkEl.textContent.trim();
        var pd = q[t];
        if (!pd || pd.chgPct == null) return;
        var chgEl = card.querySelector(".peer-chg");
        if (!chgEl) return;
        var pc = pd.chgPct;
        chgEl.textContent = (pc >= 0 ? "+" : "") + pc.toFixed(1) + "%";
        chgEl.style.color = pc >= 0 ? "#22c55e" : "#ef4444";
      });
    }).catch(function() {});
  }

  if (window.BAIZORA_LIVE_PRICES) refresh();
  setInterval(function() { if (window.BAIZORA_LIVE_PRICES && isMarketOpen()) refresh(); }, 60000);

  /* ---- Free-access-period trial CTA swap (see assets/feature_flags.js) ---- */
  if (window.FREE_ACCESS_MODE) {
    ["navTrialBtn", "ctaTrialBtn"].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) { el.href = "../signup.html"; el.textContent = "Sign Up Free"; }
    });
  }
})();
</script>
"""


def build_page_script(ticker, candle_dates_json, candle_ohlcv_json):
    return (_SCRIPT_TEMPLATE
            .replace("__DATES__", candle_dates_json)
            .replace("__OHLCV__", candle_ohlcv_json)
            .replace('"__TICKER__"', json.dumps(ticker)))


def _format_date_nice(date_str):
    """'2026-06-24' → 'June 24, 2026'"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def generate_summary(row, scan_date):
    ticker  = row["Ticker"]
    name    = row.get("CompanyName", ticker)
    price   = row.get("Price", 0) or 0
    pc1d    = row.get("PriceChange1D", 0) or 0
    pc1y    = row.get("1YPriceChange", 0) or 0
    pc3m    = row.get("3MPriceChange", 0) or 0
    pe      = row.get("PE", 0) or 0
    pe_sect = row.get("SectorAvgPE", 0) or 0
    pe_vs   = row.get("PE_vs_Sector", 0) or 0
    mcap    = row.get("MarketCap", 0) or 0
    sector  = row.get("Sector", "")
    max_pc  = row.get("1YMaxPriceChange", 0) or 0
    max_vc  = row.get("1YMaxVolumeChange", 0) or 0
    in_sp   = row.get("InSP500", False)
    in_ndq  = row.get("InNASDAQ100", False)
    is_etf  = row.get("InETF", False)

    dir1d = "gaining" if pc1d >= 0 else "declining"
    sign1d = "+" if pc1d >= 0 else ""
    sign1y = "+" if pc1y >= 0 else ""
    sign3m = "+" if pc3m >= 0 else ""
    date_label = _format_date_nice(scan_date)

    if is_etf:
        idx_str = f"an ETF tracking the {ETF_TRACKS.get(ticker, 'broader market')}"
    elif in_sp and in_ndq:
        idx_str = "a member of both the S&P 500 and Nasdaq-100"
    elif in_sp:
        idx_str = "an S&P 500 constituent"
    elif in_ndq:
        idx_str = "a Nasdaq-100 constituent"
    else:
        idx_str = "a large-cap US equity"

    pe_note = ""
    if pe and pe_sect:
        if pe_vs < -20:
            pe_note = (f" At a P/E of {pe:.1f}, it trades at a notable discount "
                       f"to the {sector} sector average of {pe_sect:.1f}.")
        elif pe_vs > 20:
            pe_note = (f" At a P/E of {pe:.1f}, it carries a premium "
                       f"to the {sector} sector average of {pe_sect:.1f}.")
        else:
            pe_note = (f" Its P/E of {pe:.1f} is roughly in line "
                       f"with the {sector} sector average of {pe_sect:.1f}.")

    # ETFs don't have a reliable market cap in our data (fundamentals are
    # intentionally blank, see ETF_TRACKS comment above) — omit that clause
    # entirely rather than print a misleading "$0B".
    mcap_clause = f"With a market cap of ${mcap:,.0f}B, {ticker} is {idx_str}." if not is_etf and mcap \
        else f"{ticker} is {idx_str}."

    noun = "fund" if is_etf else "stock"
    return (
        f"{name} ({ticker}) is {dir1d} {sign1d}{pc1d:.1f}% today ({date_label}), "
        f"trading at ${price:,.2f}. "
        f"Over the past year the {noun} is {sign1y}{pc1y:.1f}%, "
        f"with a {sign3m}{pc3m:.1f}% move over the last three months. "
        f"Its largest single-day price surge in the past year reached {max_pc:+.1f}%, "
        f"while its peak volume day ran {max_vc:+.1f}% above the 21-day average. "
        f"{mcap_clause}{pe_note}"
    )


def build_peers_html(current_ticker, peer_rows):
    """Build a row of peer stock mini-cards linking to their pages."""
    if not peer_rows:
        return ""
    cards = ""
    for r in peer_rows:
        t     = r["Ticker"]
        name  = r.get("CompanyName", t)
        short = name.split(" ")[0] if name else t   # first word of company name
        pc1d  = r.get("PriceChange1D", 0) or 0
        col   = "#22c55e" if pc1d >= 0 else "#ef4444"
        sign  = "+" if pc1d >= 0 else ""
        cards += f"""
        <a href="{t}.html" class="peer-card">
          <div class="peer-ticker">{t}</div>
          <div class="peer-name">{short}</div>
          <div class="peer-chg" style="color:{col}">{sign}{pc1d:.1f}%</div>
        </a>"""
    return f"""
  <div class="section-title">Top Nasdaq-100 Stocks</div>
  <div class="peers-grid">{cards}
  </div>
"""


def generate_page(row, scan_date, peer_rows=None, candle_dates=None, candle_ohlcv=None):
    ticker   = row["Ticker"]
    name     = row.get("CompanyName", ticker)
    price    = row.get("Price", 0) or 0
    pc1d     = row.get("PriceChange1D", 0) or 0
    sector   = row.get("Sector", "")
    pe       = row.get("PE", 0) or 0
    pe_sect  = row.get("SectorAvgPE", 0) or 0
    mcap     = row.get("MarketCap", 0) or 0
    eps      = row.get("EPS", 0) or 0
    vol1d    = row.get("VolumeM", 0) or 0
    vol_ma21 = row.get("VolumeVsMA21_1D", 0) or 0
    in_sp    = row.get("InSP500", False)
    in_ndq   = row.get("InNASDAQ100", False)
    is_etf   = row.get("InETF", False)

    color1d = "#22c55e" if pc1d >= 0 else "#ef4444"
    sign1d  = "+" if pc1d >= 0 else ""
    summary = generate_summary(row, scan_date)

    # Fundamentals are intentionally blank for ETFs (see ETF_TRACKS comment near
    # FEATURED_TICKERS) — show "—" in the stats grid instead of a misleading
    # "$0B"/"0.0"/"$0.00", matching how the dashboard already treats these fields.
    mcap_display   = f"${mcap:,.0f}B" if not is_etf else "—"
    pe_display     = f"{pe:.1f}" if not is_etf else "—"
    pe_sect_label  = f"Sector avg {pe_sect:.1f}" if not is_etf else "Not applicable to ETFs"
    eps_display    = f"${eps:.2f}" if not is_etf else "—"
    sector_display = sector if not is_etf else ETF_TRACKS.get(ticker, "ETF")

    # Inline OHLCV data for the canvas chart
    candle_dates_json = json.dumps(candle_dates or [])
    candle_ohlcv_json = json.dumps(candle_ohlcv or [])
    page_script = build_page_script(ticker, candle_dates_json, candle_ohlcv_json)

    badges = ""
    if is_etf:
        badges += f'<span class="badge">Tracks {ETF_TRACKS.get(ticker, "an index")}</span>'
    if in_sp:
        badges += '<span class="badge">S&amp;P 500</span>'
    if in_ndq:
        badges += '<span class="badge">Nasdaq-100</span>'

    timeframes = [
        ("2W", "2 Weeks"), ("1M", "1 Month"), ("3M", "3 Months"),
        ("6M", "6 Months"), ("9M", "9 Months"), ("1Y", "1 Year"),
    ]
    tf_rows = ""
    for key, label in timeframes:
        pc    = row.get(f"{key}PriceChange", 0) or 0
        maxpc = row.get(f"{key}MaxPriceChange", 0) or 0
        maxvc = row.get(f"{key}MaxVolumeChange", 0) or 0
        col   = "#22c55e" if pc >= 0 else "#ef4444"
        s     = "+" if pc >= 0 else ""
        tf_rows += f"""
        <tr>
          <td class="tf-label">{label}</td>
          <td style="color:{col};font-weight:600">{s}{pc:.1f}%</td>
          <td class="dim">{maxpc:+.1f}%</td>
          <td class="dim">{maxvc:+.1f}%</td>
        </tr>"""

    peers_html = build_peers_html(ticker, peer_rows or [])

    analysis_noun = "ETF analysis" if is_etf else "stock analysis"
    desc = f"{name} ({ticker}) {analysis_noun}: ${price:,.2f} today ({sign1d}{pc1d:.1f}%), 1-year candlestick chart with volume, MA21 ratios, and multi-timeframe performance. Updated daily."

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<!-- Google tag (gtag.js) -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-DWEPM8KFM9"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', 'G-DWEPM8KFM9');
  </script>
  <script src="../assets/feature_flags.js?v=3"></script>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{ticker} {"ETF" if is_etf else "Stock"} Analysis | {name} Price &amp; Volume Trends | Baizora</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="https://baizora.com/stocks/{ticker}.html">
  <link rel="alternate" hreflang="en" href="https://baizora.com/stocks/{ticker}.html">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://baizora.com/stocks/{ticker}.html">
  <meta property="og:title" content="{ticker} — {name} Price &amp; Volume Analysis | Baizora">
  <meta property="og:description" content="{desc}">
  <meta property="og:image" content="https://baizora.com/assets/baize_favicon_v2.png">
  <script type="application/ld+json">
  {{"@context":"https://schema.org","@type":"WebPage","name":"{ticker} {"ETF" if is_etf else "Stock"} Analysis — {name}","description":"{summary[:160].replace(chr(34), chr(39))}","url":"https://baizora.com/stocks/{ticker}.html","isPartOf":{{"@type":"WebSite","name":"Baizora","url":"https://baizora.com"}}}}
  </script>
  <link rel="icon" href="../assets/baize_favicon_v2.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@300;400;500&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --navy:#060d1f; --navy-mid:#0d1e3d; --navy-light:#162847;
      --electric:#3b82f6; --electric-bright:#60a5fa;
      --gold:#f59e0b; --green:#22c55e; --red:#ef4444;
      --white:#ffffff; --muted:#cbd5e1; --border:rgba(255,255,255,0.09);
    }}
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:'DM Sans',sans-serif;background:var(--navy);color:var(--white);min-height:100vh;}}
    a{{color:var(--electric-bright);text-decoration:none;}}
    a:hover{{text-decoration:underline;}}

    nav{{display:flex;align-items:center;justify-content:space-between;padding:18px 40px;border-bottom:1px solid var(--border);}}
    .logo-wrap{{display:flex;align-items:center;gap:10px;text-decoration:none;}}
    .logo-wrap img{{height:32px;}}
    .logo-text{{font-family:'DM Serif Display',serif;font-size:20px;color:#f8fafc;letter-spacing:-0.02em;}}
    .nav-links{{display:flex;gap:12px;align-items:center;}}
    .nav-btn{{padding:6px 16px;border-radius:8px;border:1px solid var(--border);font-size:14px;color:var(--muted);background:transparent;text-decoration:none;}}
    .nav-btn-primary{{background:var(--electric);color:white;border-color:var(--electric);}}

    .page{{max-width:1000px;margin:0 auto;padding:48px 24px 80px;}}
    .breadcrumb{{font-size:13px;color:#64748b;margin-bottom:28px;}}
    .breadcrumb a{{color:#64748b;}}
    .breadcrumb span{{margin:0 6px;}}

    .hero{{margin-bottom:36px;}}
    .company-name{{font-size:15px;color:var(--muted);margin-bottom:6px;font-family:'DM Mono',monospace;letter-spacing:0.04em;}}
    .ticker-price{{display:flex;align-items:baseline;gap:20px;flex-wrap:wrap;margin-bottom:12px;}}
    .ticker{{font-family:'DM Serif Display',serif;font-size:52px;color:var(--white);letter-spacing:-0.02em;}}
    .price{{font-size:36px;font-weight:600;}}
    .change{{font-size:22px;font-weight:600;}}
    .badges{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;}}
    .badge{{font-family:'DM Mono',monospace;font-size:12px;padding:4px 12px;border-radius:20px;background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.3);color:var(--electric-bright);}}
    .scan-date{{font-size:13px;color:#64748b;}}

    .summary-box{{background:rgba(13,30,61,0.6);border:1px solid var(--border);border-radius:16px;padding:24px 28px;margin-bottom:32px;line-height:1.75;color:var(--muted);font-size:15px;}}

    .stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:32px;}}
    .stat-card{{background:rgba(13,30,61,0.6);border:1px solid var(--border);border-radius:12px;padding:16px 20px;}}
    .stat-label{{font-family:'DM Mono',monospace;font-size:11px;color:#64748b;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px;}}
    .stat-value{{font-size:20px;font-weight:600;}}
    .stat-sub{{font-size:12px;color:#64748b;margin-top:2px;}}

    .section-title{{font-family:'DM Mono',monospace;font-size:12px;letter-spacing:0.1em;text-transform:uppercase;color:#64748b;margin-bottom:14px;}}

    .chart-box{{background:rgba(13,30,61,0.6);border:1px solid var(--border);border-radius:16px;overflow:hidden;margin-bottom:32px;}}
    .chart-box canvas{{width:100%;height:360px;display:block;}}

    .tf-box{{background:rgba(13,30,61,0.6);border:1px solid var(--border);border-radius:16px;overflow:hidden;margin-bottom:32px;}}
    table{{width:100%;border-collapse:collapse;}}
    thead th{{font-family:'DM Mono',monospace;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;padding:14px 20px;text-align:left;border-bottom:1px solid var(--border);}}
    tbody tr{{border-bottom:1px solid var(--border);}}
    tbody tr:last-child{{border-bottom:none;}}
    tbody td{{padding:14px 20px;font-size:15px;}}
    .tf-label{{font-family:'DM Mono',monospace;font-size:13px;color:var(--muted);}}
    .dim{{color:#94a3b8;}}

    .peers-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px;margin-bottom:32px;}}
    .peer-card{{background:rgba(13,30,61,0.6);border:1px solid var(--border);border-radius:12px;padding:14px 16px;text-decoration:none;transition:border-color 0.15s,background 0.15s;}}
    .peer-card:hover{{border-color:rgba(59,130,246,0.4);background:rgba(13,30,61,0.9);text-decoration:none;}}
    .peer-ticker{{font-family:'DM Mono',monospace;font-size:15px;font-weight:600;color:var(--white);margin-bottom:3px;}}
    .peer-name{{font-size:12px;color:#64748b;margin-bottom:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
    .peer-chg{{font-family:'DM Mono',monospace;font-size:13px;font-weight:600;}}

    .cta-box{{background:linear-gradient(135deg,rgba(59,130,246,0.1),rgba(245,158,11,0.08));border:1px solid rgba(59,130,246,0.2);border-radius:16px;padding:32px;text-align:center;}}
    .cta-box h3{{font-family:'DM Serif Display',serif;font-size:24px;margin-bottom:10px;}}
    .cta-box p{{color:var(--muted);margin-bottom:20px;font-size:15px;}}
    .btn-gold{{display:inline-block;padding:12px 32px;border-radius:10px;background:linear-gradient(135deg,#f59e0b,#d97706);color:white;font-weight:600;font-size:15px;text-decoration:none;}}

    footer{{border-top:1px solid var(--border);padding:24px 40px;text-align:center;font-size:13px;color:#475569;line-height:2;}}

    @media(max-width:600px){{
      nav{{padding:14px 20px;}}
      .page{{padding:32px 16px 60px;}}
      .ticker{{font-size:38px;}} .price{{font-size:26px;}}
      .peers-grid{{grid-template-columns:repeat(auto-fill,minmax(100px,1fr));}}
      .chart-box canvas{{height:260px;}}
    }}
  </style>
</head>
<body>

<nav>
  <a href="../" class="logo-wrap">
    <img src="../assets/baize_favicon_v2.png" alt="Baizora">
    <span class="logo-text">Baiz<span style="color:#3b82f6;">ora</span></span>
  </a>
  <div class="nav-links">
    <a href="../baizora_main_form_freetier.html" class="nav-btn">Free Tier</a>
    <a href="../pricing.html" class="nav-btn nav-btn-primary" id="navTrialBtn">Start Free Trial</a>
  </div>
</nav>

<div class="page">

  <div class="breadcrumb">
    <a href="../">Home</a><span>›</span>Stocks<span>›</span>{ticker}
  </div>

  <div class="hero">
    <div class="company-name">{name}</div>
    <div class="ticker-price">
      <div class="ticker">{ticker}</div>
      <div class="price">${price:,.2f}</div>
      <div class="change" style="color:{color1d}">{sign1d}{pc1d:.1f}%</div>
    </div>
    <div class="badges">{badges}</div>
    <div class="scan-date">Data as of {scan_date} &nbsp;·&nbsp; Updated daily after market close</div>
  </div>

  <div class="summary-box">{summary}</div>

  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">Market Cap</div>
      <div class="stat-value">{mcap_display}</div>
      <div class="stat-sub">{sector_display}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">P/E Ratio</div>
      <div class="stat-value">{pe_display}</div>
      <div class="stat-sub">{pe_sect_label}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">EPS (TTM)</div>
      <div class="stat-value">{eps_display}</div>
      <div class="stat-sub">{"Not applicable to ETFs" if is_etf else "Trailing twelve months"}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Volume</div>
      <div class="stat-value">{vol1d:.1f}M</div>
      <div class="stat-sub">Vol / MA21: {vol_ma21:.2f}x</div>
    </div>
  </div>

  <div class="section-title" id="chartSectionTitle">1-Year Candlestick &amp; Volume &nbsp;·&nbsp; Scan date: {scan_date}</div>
  <div class="chart-box">
    <canvas id="stockChart"></canvas>
  </div>

  <div class="section-title">Multi-Timeframe Performance</div>
  <div class="tf-box">
    <table>
      <thead>
        <tr>
          <th>Period</th>
          <th>Price Change</th>
          <th>Peak Day Gain</th>
          <th>Peak Vol Spike</th>
        </tr>
      </thead>
      <tbody>{tf_rows}
      </tbody>
    </table>
  </div>

  {peers_html}

  <div class="cta-box">
    <h3>See all 500+ stocks</h3>
    <p>Sort by any signal across 7 timeframes. Full S&amp;P 500 and Nasdaq-100 coverage, updated daily.</p>
    <a href="../pricing.html" class="btn-gold" id="ctaTrialBtn">Start 7-Day Free Trial</a>
  </div>

</div>

<footer>
  <a href="../">Baizora</a> &nbsp;·&nbsp;
  <a href="../assets/about.html">About</a> &nbsp;·&nbsp;
  <a href="../assets/faq.html">FAQ</a> &nbsp;·&nbsp;
  <a href="../assets/privacy.html">Privacy</a> &nbsp;·&nbsp;
  <a href="../assets/disclaimer.html">Disclaimer</a>
  <br>
  For informational purposes only. Not financial advice. Data updated daily after US market close.
  <br>
  <span style="font-family:'DM Mono',monospace;font-size:11px;letter-spacing:0.04em;">Market Data Sourced by <a href="https://www.tiingo.com" target="_blank" rel="noopener" style="color:#475569;text-decoration:none;">Tiingo.com</a></span>
</footer>

{page_script}
</body>
</html>"""


def main():
    import sys
    data      = json.load(open(DATA_FILE))
    scan_date = data["date"]
    ticker_map = {r["Ticker"]: r for r in data["data"]}

    # Load candle data for chart embedding
    candle_dates = []
    candle_data  = {}
    if CANDLES_FILE.exists():
        cj = json.load(open(CANDLES_FILE))
        candle_dates = cj.get("dates", [])
        candle_data  = cj.get("data", {})
    else:
        print("[warn] candles.json not found — charts will be empty")

    tickers = sys.argv[1:] if len(sys.argv) > 1 else FEATURED_TICKERS
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Determine if we're generating the top-10 set (to wire up peer links)
    top10_rows = [ticker_map[t] for t in TOP10_NASDAQ if t in ticker_map]

    for ticker in tickers:
        if ticker not in ticker_map:
            print(f"[skip] {ticker} not in data")
            continue
        # Pass sibling rows (excluding self) as peers when ticker is in TOP10
        if ticker in TOP10_NASDAQ:
            peers = [r for r in top10_rows if r["Ticker"] != ticker]
        else:
            peers = []
        html = generate_page(
            ticker_map[ticker], scan_date,
            peer_rows=peers,
            candle_dates=candle_dates,
            candle_ohlcv=candle_data.get(ticker, []),
        )
        out  = OUTPUT_DIR / f"{ticker}.html"
        out.write_text(html, encoding="utf-8")
        print(f"[ok] {out}")


if __name__ == "__main__":
    main()
