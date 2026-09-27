/* Opens the main dashboard's standard candlestick chart (the #tickerModal in
   baizora_main_form(_cn).html) in an overlay on the current page, instead of the
   lighter BaizoraChart popup. Load it right after candlestick-chart.js.

   The dashboard is iframed once in chart-only mode (?embed=1) and reused; tickers
   are posted to it. Links of the form baizora_main_form(_cn).html?chart=T are
   intercepted (ctrl/cmd-click still opens the full dashboard). If the viewer
   isn't signed in / subscribed, the dashboard reports bz-chart-auth and we fall
   back to the original BaizoraChart popup. */
(function () {
  const CN = /_cn\.html$/i.test(location.pathname);
  const PAGE = new URL('../baizora_main_form' + (CN ? '_cn' : '') + '.html',
    document.currentScript.src).href;
  const TXT = CN ? { loading: '图表加载中…', failed: '图表加载失败。' }
                 : { loading: 'Loading chart…', failed: "Couldn't load the chart." };
  const orig = window.BaizoraChart ? window.BaizoraChart.open : null;
  let wrap = null, frame = null, ready = false, blocked = false, pending = null, timer = null;

  function build() {
    wrap = document.createElement('div');
    wrap.id = 'bzMainChart';
    wrap.style.cssText = 'display:none;position:fixed;inset:0;z-index:10000;';
    wrap.innerHTML = '<div id="bzMainChartMsg" style="position:absolute;inset:0;background:rgba(6,13,31,0.88);display:flex;align-items:center;justify-content:center;gap:14px;font-family:&quot;DM Mono&quot;,monospace;font-size:13px;color:#cbd5e1;"><span id="bzMainChartTxt"></span><button type="button" id="bzMainChartX" style="background:none;border:none;color:#cbd5e1;font-size:18px;cursor:pointer;">✕</button></div>';
    frame = document.createElement('iframe');
    frame.title = 'Chart';
    frame.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;border:0;background:transparent;';
    frame.setAttribute('allowtransparency', 'true');
    frame.src = PAGE + '?embed=1';
    wrap.appendChild(frame);
    document.body.appendChild(wrap);
    document.getElementById('bzMainChartX').onclick = hide;
  }
  function msg(show, txt) {
    document.getElementById('bzMainChartMsg').style.display = show ? 'flex' : 'none';
    frame.style.visibility = show ? 'hidden' : 'visible';
    if (txt) document.getElementById('bzMainChartTxt').textContent = txt;
  }
  function hide() {
    if (!wrap) return;
    clearTimeout(timer);
    wrap.style.display = 'none';
    document.body.style.overflow = '';
  }
  function send(t) {
    msg(false);
    frame.contentWindow.postMessage({ type: 'bz-chart-open', ticker: t }, location.origin);
    frame.focus();
  }
  function open(t, meta) {
    t = String(t || '').toUpperCase();
    if (!t) return;
    if (blocked) { if (orig) orig(t, meta); return; }
    if (!wrap) build();
    wrap.style.display = 'block';
    document.body.style.overflow = 'hidden';
    if (ready) { send(t); return; }
    pending = { t, meta };
    msg(true, TXT.loading);
    clearTimeout(timer);
    timer = setTimeout(() => { if (!ready) msg(true, TXT.failed); }, 30000);
  }

  window.addEventListener('message', e => {
    if (e.origin !== location.origin || !frame || e.source !== frame.contentWindow || !e.data) return;
    const type = e.data.type;
    if (type === 'bz-chart-ready') {
      ready = true;
      clearTimeout(timer);
      if (pending && wrap.style.display !== 'none') send(pending.t);
      pending = null;
    } else if (type === 'bz-chart-auth') {
      blocked = true;
      const p = pending;
      pending = null;
      hide();
      if (wrap) { wrap.remove(); wrap = frame = null; }
      if (p && orig) orig(p.t, p.meta);
    } else if (type === 'bz-chart-close' || type === 'bz-chart-missing') {
      hide();
    }
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && wrap && wrap.style.display !== 'none') hide();
  });
  document.addEventListener('click', e => {
    if (e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest && e.target.closest('a[href]');
    if (!a || a.href.indexOf(PAGE + '?chart=') !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    open(new URL(a.href).searchParams.get('chart'));
  }, true);

  if (window.BaizoraChart) {
    const url = t => PAGE + '?chart=' + encodeURIComponent(t);
    window.BaizoraChart.open = open;
    window.BaizoraChart.hasDedicatedPage = () => false;
    window.BaizoraChart.tickerLinkHtml = (t, cls) => '<a href="' + url(t) + '" class="' + cls + '">' + t + '</a>';
  }
})();
