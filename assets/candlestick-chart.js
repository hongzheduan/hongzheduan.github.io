/* Shared candlestick chart modal.
   Used by public data pages (top-price-movers.html, unusual-volume.html) that
   list many tickers but only have dedicated stocks/*.html pages for a subset.
   Fetches data/candles.json once and renders a price+volume candlestick chart
   in a modal instead of linking to a page that may not exist. */
(function () {
  // Tickers with a dedicated stocks/TICKER.html page — link there instead of the modal.
  const DEDICATED_PAGES = new Set([
    'AAPL', 'ABNB', 'AMD', 'AMZN', 'AVGO', 'COIN', 'CRM', 'CRWD', 'GOOGL', 'META',
    'MSFT', 'MU', 'NFLX', 'NOW', 'NVDA', 'ORCL', 'PANW', 'PLTR', 'QQQ', 'SMCI',
    'TSLA', 'UBER', 'VOO', 'WMT'
  ]);

  const HOLIDAYS = new Set([
    '2024-01-01', '2024-01-15', '2024-02-19', '2024-03-29', '2024-05-27', '2024-06-19',
    '2024-07-04', '2024-09-02', '2024-11-28', '2024-12-25',
    '2025-01-01', '2025-01-20', '2025-02-17', '2025-04-18', '2025-05-26', '2025-06-19',
    '2025-07-04', '2025-09-01', '2025-11-27', '2025-12-25',
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19',
    '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
    '2027-01-01', '2027-01-18', '2027-02-15', '2027-04-02', '2027-05-31', '2027-06-18',
    '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24',
  ]);

  function fillCalendarGaps(dates, candles) {
    const rd = [], rc = [];
    for (let i = 0; i < dates.length; i++) {
      if (i > 0) {
        const prev = new Date(dates[i - 1] + 'T12:00:00Z');
        const curr = new Date(dates[i] + 'T12:00:00Z');
        const d = new Date(prev);
        d.setUTCDate(d.getUTCDate() + 1);
        while (d < curr) {
          const dow = d.getUTCDay();
          const ds = d.toISOString().slice(0, 10);
          if (dow !== 0 && dow !== 6 && !HOLIDAYS.has(ds)) {
            rd.push(ds); rc.push(null);
          }
          d.setUTCDate(d.getUTCDate() + 1);
        }
      }
      rd.push(dates[i]); rc.push(candles[i]);
    }
    return { dates: rd, candles: rc };
  }

  function renderCandleChart(canvas, candles, dates) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    const W = rect.width, H = rect.height;
    const hasVol = candles.some(c => c && c[4] > 0);
    const volH = hasVol ? Math.round(H * 0.22) : 0;
    const gap = hasVol ? 6 : 0;
    const pad = { top: 20, right: 16, bottom: 28, left: 58 };
    const priceH = H - pad.top - pad.bottom - volH - gap;
    const n = candles.length;
    const slotW = (W - pad.left - pad.right) / n;
    const cndW = Math.max(1, slotW * 0.65);
    const toX = i => pad.left + i * slotW + (slotW - cndW) / 2;
    let minP = Infinity, maxP = -Infinity;
    candles.forEach(c => { if (!c) return; const [, h, l] = c; if (h > maxP) maxP = h; if (l < minP) minP = l; });
    const buf = (maxP - minP) * 0.05 || 1;
    const lo = minP - buf, hi = maxP + buf;
    const toY = p => pad.top + priceH * (1 - (p - lo) / (hi - lo));
    ctx.clearRect(0, 0, W, H);
    ctx.font = `11px 'DM Mono', monospace`;
    ctx.textAlign = 'right';
    for (let i = 0; i <= 4; i++) {
      const p = lo + (hi - lo) * (i / 4);
      const y = toY(p);
      ctx.strokeStyle = 'rgba(255,255,255,0.06)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(W - pad.right, y); ctx.stroke();
      ctx.fillStyle = '#64748b';
      ctx.fillText(p >= 1000 ? p.toFixed(0) : p.toFixed(2), pad.left - 5, y + 4);
    }
    const latestDate = new Date(dates[dates.length - 1] + 'T12:00:00');
    ctx.font = `10px 'DM Mono', monospace`;
    ctx.fillStyle = '#475569';
    ctx.fillText(
      latestDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
      W - pad.right, pad.top - 4
    );
    ctx.font = `11px 'DM Mono', monospace`;
    ctx.textAlign = 'center';
    let lastMo = -1, lastYr = -1, moCount = 0;
    dates.forEach((d, i) => {
      const dt = new Date(d + 'T12:00:00');
      const mo = dt.getMonth(), yr = dt.getFullYear();
      const isLast = i === n - 1;
      if (n < 100) {
        if (i % Math.round(n / 6) !== 0 && !isLast) return;
        ctx.fillStyle = isLast ? '#94a3b8' : '#64748b';
        ctx.fillText(dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }), toX(i) + cndW / 2, H - 8);
      } else {
        if (mo === lastMo && !isLast) return;
        if (!isLast) { lastMo = mo; moCount++; }
        if (n >= 200 && moCount % 2 === 0 && !isLast) return;
        const moName = dt.toLocaleDateString('en-US', { month: 'short' });
        const label = isLast
          ? dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
          : (yr !== lastYr ? `${moName} '${String(yr).slice(-2)}` : moName);
        if (!isLast) lastYr = yr;
        ctx.fillStyle = isLast ? '#94a3b8' : '#64748b';
        ctx.fillText(label, toX(i) + cndW / 2, H - 8);
      }
    });
    candles.forEach((c, i) => {
      if (!c) return;
      const [o, h, l, cv] = c;
      const green = cv >= o;
      const x = toX(i), mid = x + cndW / 2;
      ctx.strokeStyle = green ? '#22c55e' : '#ef4444';
      ctx.fillStyle = green ? 'rgba(34,197,94,0.75)' : 'rgba(239,68,68,0.75)';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(mid, toY(h)); ctx.lineTo(mid, toY(l)); ctx.stroke();
      const bTop = toY(Math.max(o, cv));
      const bH = Math.max(1, toY(Math.min(o, cv)) - bTop);
      ctx.fillRect(x, bTop, cndW, bH);
      ctx.strokeRect(x, bTop, cndW, bH);
    });
    if (hasVol) {
      const volTop = pad.top + priceH + gap;
      const maxVol = Math.max(...candles.map(c => c ? c[4] || 0 : 0));
      ctx.strokeStyle = 'rgba(255,255,255,0.06)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pad.left, volTop); ctx.lineTo(W - pad.right, volTop); ctx.stroke();
      ctx.fillStyle = '#475569'; ctx.font = `9px 'DM Mono', monospace`;
      ctx.textAlign = 'right';
      ctx.fillText('VOL', pad.left - 5, volTop + 9);
      candles.forEach((c, i) => {
        if (!c || !c[4]) return;
        const [o, , , cv, v] = c;
        const green = cv >= o;
        const bH = Math.round((v / maxVol) * (volH - 4));
        ctx.fillStyle = green ? 'rgba(34,197,94,0.45)' : 'rgba(239,68,68,0.45)';
        ctx.fillRect(toX(i), volTop + (volH - 4) - bH, cndW, bH);
      });
    }
  }

  const CSS = `
    #bzChartModal { display:none; position:fixed; inset:0; background:rgba(6,13,31,0.85); backdrop-filter:blur(4px); z-index:1000; align-items:center; justify-content:center; padding:16px; }
    #bzChartModal .bz-card { background:#0d1e3d; border:1px solid rgba(59,130,246,0.25); border-radius:16px; width:100%; max-width:720px; max-height:90vh; overflow-y:auto; padding:24px; position:relative; }
    #bzChartClose { position:absolute; top:16px; right:16px; background:none; border:none; color:#94a3b8; font-size:20px; line-height:1; cursor:pointer; padding:4px; }
    #bzChartClose:hover { color:#fff; }
    .bz-chart-head { display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; padding-right:28px; }
    #bzChartTicker { font-family:'DM Mono',monospace; font-size:22px; font-weight:700; color:#fff; letter-spacing:.05em; }
    #bzChartPrice { font-size:18px; color:#60a5fa; font-weight:600; }
    #bzChartChg { font-size:15px; font-weight:600; }
    #bzChartName { color:#94a3b8; font-size:13px; margin:4px 0 20px; font-family:'DM Sans',sans-serif; }
    #bzChartDesc { display:none; margin:18px 0 0; padding-top:16px; border-top:1px solid rgba(255,255,255,0.08); font-family:'DM Sans',sans-serif; color:#cbd5e1; font-size:13px; line-height:1.65; }
    .bz-desc-source { display:none; color:#60a5fa; text-decoration:none; font-family:'DM Mono',monospace; font-size:10.5px; letter-spacing:.04em; }
    .bz-desc-source:hover { text-decoration:underline; }
    .bz-desc-sep { display:none; color:#475569; }
    .bz-tf-row { display:flex; gap:6px; margin-bottom:16px; flex-wrap:wrap; }
    .bz-tf-btn { font-family:'DM Mono',monospace; font-size:11px; letter-spacing:.05em; padding:5px 12px; border-radius:6px; border:1px solid rgba(255,255,255,0.09); background:transparent; color:#94a3b8; cursor:pointer; }
    .bz-tf-btn:hover { border-color:rgba(59,130,246,0.4); color:#fff; }
    .bz-tf-btn.active { border-color:rgba(59,130,246,0.4); background:rgba(59,130,246,0.12); color:#60a5fa; }
    #bzChartCanvas { width:100%; height:340px; display:block; }
    .bz-chart-msg { text-align:center; padding:60px 20px; color:#64748b; font-family:'DM Mono',monospace; font-size:12px; letter-spacing:.05em; }
    @media (max-width:600px) { #bzChartCanvas { height:260px; } }
  `;

  const TF_OPTIONS = [
    { label: '1M', days: 21 },
    { label: '3M', days: 63 },
    { label: '6M', days: 126 },
    { label: '1Y', days: 252 },
  ];

  let candleData = null;
  let candleFetchPromise = null;
  function loadCandles() {
    if (!candleFetchPromise) {
      candleFetchPromise = fetch('data/candles.json')
        .then(r => r.json())
        .then(d => { candleData = d; return d; })
        .catch(() => { candleData = null; });
    }
    return candleFetchPromise;
  }

  let descData = null;
  let descFetchPromise = null;
  function loadDescriptions() {
    if (!descFetchPromise) {
      descFetchPromise = fetch('data/company_descriptions.json')
        .then(r => r.json())
        .then(d => { descData = d; return d; })
        .catch(() => { descData = null; });
    }
    return descFetchPromise;
  }

  // Shown at the bottom of the chart as supplementary info, so unlike a header
  // blurb there's no space pressure — full text, no truncation/expand needed.
  function drawDescription() {
    const wrap = document.getElementById('bzChartDesc');
    const bodyEl = document.getElementById('bzChartDescBody');
    const sepEl = document.getElementById('bzChartDescSep');
    const sourceEl = document.getElementById('bzChartDescSource');
    if (!wrap || !state.ticker) return;
    const d = descData && descData[state.ticker];
    if (!d || !d.description) { wrap.style.display = 'none'; return; }

    wrap.style.display = 'block';
    bodyEl.textContent = d.description;
    if (d.wiki_url) {
      sourceEl.href = d.wiki_url;
      sourceEl.style.display = 'inline';
      sepEl.style.display = 'inline';
    } else {
      sourceEl.style.display = 'none';
      sepEl.style.display = 'none';
    }
  }

  const state = { ticker: null, tf: 126 };
  let modalBuilt = false;

  function ensureModal() {
    if (modalBuilt) return;
    modalBuilt = true;
    const style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);

    const tfBtns = TF_OPTIONS.map(o =>
      `<button class="bz-tf-btn${o.days === state.tf ? ' active' : ''}" data-tf="${o.days}">${o.label}</button>`
    ).join('');

    const wrap = document.createElement('div');
    wrap.id = 'bzChartModal';
    wrap.innerHTML = `
      <div class="bz-card">
        <button id="bzChartClose" aria-label="Close">✕</button>
        <div class="bz-chart-head">
          <span id="bzChartTicker"></span>
          <span id="bzChartPrice"></span>
          <span id="bzChartChg"></span>
        </div>
        <div id="bzChartName"></div>
        <div class="bz-tf-row">${tfBtns}</div>
        <div id="bzChartBody">
          <div id="bzChartMsg" class="bz-chart-msg" style="display:none;"></div>
          <canvas id="bzChartCanvas"></canvas>
        </div>
        <div id="bzChartDesc"><span id="bzChartDescBody"></span><span id="bzChartDescSep" class="bz-desc-sep"> · </span><a id="bzChartDescSource" class="bz-desc-source" href="#" target="_blank" rel="noopener">SOURCE ↗</a></div>
      </div>
    `;
    document.body.appendChild(wrap);

    document.getElementById('bzChartClose').addEventListener('click', close);
    wrap.addEventListener('click', e => { if (e.target === wrap) close(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && wrap.style.display === 'flex') close(); });
    wrap.querySelectorAll('.bz-tf-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        state.tf = parseInt(btn.dataset.tf, 10);
        wrap.querySelectorAll('.bz-tf-btn').forEach(b => b.classList.toggle('active', b === btn));
        draw();
      });
    });
    window.addEventListener('resize', () => {
      if (wrap.style.display !== 'flex') return;
      draw();
    });
  }

  function draw() {
    const canvas = document.getElementById('bzChartCanvas');
    const msg = document.getElementById('bzChartMsg');
    if (!canvas || !state.ticker) return;
    if (!candleData) {
      msg.textContent = 'Loading chart…';
      msg.style.display = 'block';
      canvas.style.display = 'none';
      return;
    }
    const raw = candleData.data && candleData.data[state.ticker];
    if (!raw) {
      msg.textContent = 'Chart data not available for this ticker yet.';
      msg.style.display = 'block';
      canvas.style.display = 'none';
      return;
    }
    msg.style.display = 'none';
    canvas.style.display = 'block';
    const { dates, candles } = fillCalendarGaps(candleData.dates || [], raw);
    const n = candles.length;
    const tf = Math.min(state.tf, n);
    renderCandleChart(canvas, candles.slice(-tf), dates.slice(-tf));
  }

  function open(ticker, meta) {
    ensureModal();
    meta = meta || {};
    state.ticker = ticker;
    state.tf = 126;
    document.getElementById('bzChartTicker').textContent = ticker;
    document.getElementById('bzChartName').textContent = meta.name || '';
    document.getElementById('bzChartPrice').textContent = meta.price != null ? '$' + meta.price.toFixed(2) : '';
    const chgEl = document.getElementById('bzChartChg');
    if (meta.chg != null) {
      chgEl.textContent = (meta.chg >= 0 ? '+' : '') + meta.chg.toFixed(2) + '%';
      chgEl.style.color = meta.chg >= 0 ? '#22c55e' : '#ef4444';
    } else {
      chgEl.textContent = '';
    }
    document.querySelectorAll('#bzChartModal .bz-tf-btn').forEach(b => b.classList.toggle('active', b.dataset.tf === '126'));
    document.getElementById('bzChartModal').style.display = 'flex';
    document.body.style.overflow = 'hidden';
    draw();
    loadCandles().then(draw);
    drawDescription();
    loadDescriptions().then(drawDescription);
  }

  function close() {
    const wrap = document.getElementById('bzChartModal');
    if (wrap) wrap.style.display = 'none';
    document.body.style.overflow = '';
  }

  function tickerLinkHtml(ticker, className) {
    if (DEDICATED_PAGES.has(ticker)) {
      return `<a href="stocks/${ticker}.html" class="${className}">${ticker}</a>`;
    }
    return `<a href="javascript:void(0)" class="${className} bz-chart-link" data-ticker="${ticker}">${ticker}</a>`;
  }

  window.BaizoraChart = { open, close, tickerLinkHtml, hasDedicatedPage: t => DEDICATED_PAGES.has(t) };
})();
