(function () {
  'use strict';

  var scriptTag = document.currentScript;
  var lang = (scriptTag && scriptTag.dataset.lang) || 'en';
  var isCN = lang === 'cn';
  var isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  var API_URL = isLocal
    ? 'http://127.0.0.1:5001/baizora/us-central1/api/chat'
    : 'https://us-central1-baizora.cloudfunctions.net/api/chat';

  var T = {
    title:       isCN ? '贝佐拉 AI 助手' : 'Baizora Assistant',
    placeholder: isCN ? '输入您的问题…' : 'Ask me about Baizora…',
    send:        isCN ? '发送' : 'Send',
    greeting:    isCN
      ? '您好！我是贝佐拉 AI 助手，可以回答关于功能、价格方案、数据指标和注册流程的问题。有什么可以帮您？'
      : "Hi! I'm Baizora's AI assistant. Ask me about features, pricing, dashboard columns, or how to sign up.",
    error:       isCN ? '抱歉，出现了错误，请稍后重试。' : 'Sorry, something went wrong. Please try again.',
    limit:       isCN ? '已达本次对话上限，请刷新页面重新开始。' : 'Session limit reached. Please refresh to start a new chat.',
    ask:         isCN ? '问' : 'Ask',
  };

  var MAX_TURNS = 10;
  var history = [];
  var turnCount = 0;
  var isSending = false;
  var panelOpen = false;
  var initialized = false;

  /* ---- CSS ---- */
  var styleEl = document.createElement('style');
  styleEl.textContent = [
    '#bzw-btn{',
      'position:fixed;bottom:24px;right:24px;z-index:9999;',
      'height:52px;padding:0 18px 0 12px;border-radius:26px;',
      'background:linear-gradient(135deg,#3b82f6,#1d4ed8);',
      'border:none;cursor:pointer;',
      'box-shadow:0 4px 20px rgba(59,130,246,.45);',
      'display:flex;align-items:center;justify-content:center;gap:7px;',
      'transition:transform .2s,box-shadow .2s;',
      'animation:bzw-float 3s ease-in-out infinite;',
    '}',
    '#bzw-btn:hover{animation:none;transform:scale(1.06);box-shadow:0 6px 28px rgba(59,130,246,.6);}',
    '#bzw-btn svg{width:28px;height:28px;fill:#fff;pointer-events:none;flex-shrink:0;}',
    '#bzw-btn span{font-size:14px;font-weight:600;color:#fff;letter-spacing:.03em;pointer-events:none;}',
    '@keyframes bzw-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}',

    '#bzw-panel{',
      'position:fixed;bottom:92px;right:24px;z-index:9998;',
      'width:360px;height:520px;',
      'max-width:calc(100vw - 32px);max-height:calc(100vh - 120px);',
      'background:#060d1f;',
      'border:1px solid rgba(255,255,255,.09);',
      'border-radius:16px;',
      'display:flex;flex-direction:column;',
      "font-family:'DM Sans',-apple-system,BlinkMacSystemFont,sans-serif;",
      'box-shadow:0 20px 60px rgba(0,0,0,.65);',
      'opacity:0;transform:translateY(16px) scale(.97);pointer-events:none;',
      'transition:opacity .22s ease,transform .22s ease;',
    '}',
    '#bzw-panel.bzw-on{opacity:1;transform:translateY(0) scale(1);pointer-events:all;}',

    '#bzw-hd{',
      'display:flex;align-items:center;justify-content:space-between;',
      'padding:13px 16px;',
      'background:rgba(13,30,61,.8);',
      'border-bottom:1px solid rgba(255,255,255,.08);',
      'border-radius:16px 16px 0 0;flex-shrink:0;',
    '}',
    '.bzw-hl{display:flex;align-items:center;gap:8px;}',
    '.bzw-dot{width:8px;height:8px;border-radius:50%;background:#22c55e;animation:bzw-p 2.4s ease infinite;}',
    '@keyframes bzw-p{0%,100%{opacity:1}50%{opacity:.35}}',
    '.bzw-ttl{font-size:13.5px;font-weight:600;color:#f1f5f9;}',

    '#bzw-x{',
      'background:none;border:none;cursor:pointer;color:#64748b;',
      'padding:4px;border-radius:6px;display:flex;align-items:center;',
      'transition:color .15s,background .15s;',
    '}',
    '#bzw-x:hover{color:#f1f5f9;background:rgba(255,255,255,.07);}',
    '#bzw-x svg{width:15px;height:15px;}',

    '#bzw-msgs{',
      'flex:1;overflow-y:auto;padding:14px 14px 8px;',
      'display:flex;flex-direction:column;gap:10px;',
      'scroll-behavior:smooth;',
    '}',
    '#bzw-msgs::-webkit-scrollbar{width:4px;}',
    '#bzw-msgs::-webkit-scrollbar-track{background:transparent;}',
    '#bzw-msgs::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:2px;}',

    '.bzw-m{max-width:86%;padding:9px 12px;font-size:13.5px;line-height:1.55;word-break:break-word;}',
    '.bzw-bot{',
      'background:rgba(13,30,61,.75);',
      'border:1px solid rgba(255,255,255,.07);',
      'color:#e2e8f0;align-self:flex-start;border-radius:4px 12px 12px 12px;',
    '}',
    '.bzw-usr{',
      'background:linear-gradient(135deg,#3b82f6,#2563eb);',
      'color:#fff;align-self:flex-end;border-radius:12px 4px 12px 12px;',
    '}',
    '.bzw-typ{',
      'background:rgba(13,30,61,.75);border:1px solid rgba(255,255,255,.07);',
      'align-self:flex-start;border-radius:4px 12px 12px 12px;padding:10px 14px;',
    '}',
    '.bzw-da span{',
      'display:inline-block;width:6px;height:6px;border-radius:50%;',
      'background:#64748b;margin:0 2px;animation:bzw-d 1.4s ease infinite;',
    '}',
    '.bzw-da span:nth-child(2){animation-delay:.2s;}',
    '.bzw-da span:nth-child(3){animation-delay:.4s;}',
    '@keyframes bzw-d{0%,80%,100%{transform:scale(.7);opacity:.4}40%{transform:scale(1);opacity:1}}',

    '#bzw-ft{',
      'display:flex;align-items:center;gap:8px;padding:10px 12px;',
      'border-top:1px solid rgba(255,255,255,.08);',
      'background:rgba(6,13,31,.7);',
      'border-radius:0 0 16px 16px;flex-shrink:0;',
    '}',
    '#bzw-in{',
      'flex:1;background:rgba(13,30,61,.6);',
      'border:1px solid rgba(255,255,255,.11);border-radius:10px;',
      'padding:8px 11px;color:#f1f5f9;font-size:13.5px;font-family:inherit;',
      'outline:none;transition:border-color .15s;',
    '}',
    '#bzw-in::placeholder{color:#475569;}',
    '#bzw-in:focus{border-color:rgba(59,130,246,.45);}',

    '#bzw-sd{',
      'width:34px;height:34px;flex-shrink:0;border-radius:9px;',
      'background:linear-gradient(135deg,#3b82f6,#2563eb);',
      'border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;',
      'transition:opacity .15s,transform .15s;',
    '}',
    '#bzw-sd:hover:not(:disabled){transform:scale(1.06);}',
    '#bzw-sd:disabled{opacity:.4;cursor:default;}',
    '#bzw-sd svg{width:15px;height:15px;fill:#fff;}',

    '@media(max-width:480px){',
      '#bzw-panel{width:calc(100vw - 20px);right:10px;bottom:112px;}',
      '#bzw-btn{bottom:72px;right:14px;height:44px;padding:0 14px 0 10px;gap:6px;}',
      '#bzw-btn span{font-size:13px;}',
      '#bzw-btn svg{width:24px;height:24px;}',
    '}',
  ].join('');
  document.head.appendChild(styleEl);

  /* ---- DOM ---- */
  var btn = document.createElement('button');
  btn.id = 'bzw-btn';
  btn.setAttribute('aria-label', T.title);
  btn.innerHTML = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">' +
    '<circle cx="12" cy="2" r="1.4"/>' +
    '<rect x="11.3" y="3.2" width="1.4" height="2.4" rx="0.5"/>' +
    '<rect x="2.5" y="5.5" width="19" height="13" rx="3.5"/>' +
    '<circle cx="8.5" cy="11" r="2.1" style="fill:#0d1e3d"/>' +
    '<circle cx="9.3" cy="10.2" r="0.65" style="fill:#fff"/>' +
    '<circle cx="15.5" cy="11" r="2.1" style="fill:#0d1e3d"/>' +
    '<circle cx="16.3" cy="10.2" r="0.65" style="fill:#fff"/>' +
    '<path d="M8.5 14.8 Q12 17 15.5 14.8" style="fill:none;stroke:#0d1e3d;stroke-width:1.5;stroke-linecap:round"/>' +
    '</svg>' +
    '<span>' + T.ask + '</span>';

  var panel = document.createElement('div');
  panel.id = 'bzw-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', T.title);
  panel.innerHTML =
    '<div id="bzw-hd">' +
      '<div class="bzw-hl"><span class="bzw-dot"></span><span class="bzw-ttl">' + T.title + '</span></div>' +
      '<button id="bzw-x" aria-label="Close">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">' +
          '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>' +
        '</svg>' +
      '</button>' +
    '</div>' +
    '<div id="bzw-msgs"></div>' +
    '<div id="bzw-ft">' +
      '<input id="bzw-in" type="text" placeholder="' + T.placeholder + '" maxlength="500" autocomplete="off">' +
      '<button id="bzw-sd" aria-label="' + T.send + '">' +
        '<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>' +
      '</button>' +
    '</div>';

  var _root = document.documentElement || document.body;
  _root.appendChild(btn);
  _root.appendChild(panel);

  var msgsEl = document.getElementById('bzw-msgs');
  var inputEl = document.getElementById('bzw-in');
  var sendEl  = document.getElementById('bzw-sd');

  /* ---- helpers ---- */
  function addMsg(text, role) {
    var el = document.createElement('div');
    el.className = 'bzw-m ' + (role === 'user' ? 'bzw-usr' : 'bzw-bot');
    el.textContent = text;
    msgsEl.appendChild(el);
    msgsEl.scrollTop = msgsEl.scrollHeight;
    return el;
  }

  function addTyping() {
    var el = document.createElement('div');
    el.className = 'bzw-typ';
    el.innerHTML = '<div class="bzw-da"><span></span><span></span><span></span></div>';
    msgsEl.appendChild(el);
    msgsEl.scrollTop = msgsEl.scrollHeight;
    return el;
  }

  function openPanel() {
    panelOpen = true;
    panel.classList.add('bzw-on');
    if (!initialized) {
      initialized = true;
      addMsg(T.greeting, 'assistant');
    }
    requestAnimationFrame(function () { inputEl.focus(); });
  }

  function closePanel() {
    panelOpen = false;
    panel.classList.remove('bzw-on');
  }

  /* ---- send ---- */
  function send() {
    var text = inputEl.value.trim();
    if (!text || isSending) return;
    if (turnCount >= MAX_TURNS) { addMsg(T.limit, 'assistant'); return; }

    inputEl.value = '';
    isSending = true;
    sendEl.disabled = true;
    turnCount++;

    addMsg(text, 'user');
    var typEl = addTyping();

    fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, history: history.slice(-10), lang: lang }),
    })
    .then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    })
    .then(function (data) {
      typEl.remove();
      var reply = (data && data.reply) ? data.reply : T.error;
      addMsg(reply, 'assistant');
      history.push({ role: 'user', content: text });
      history.push({ role: 'assistant', content: reply });
      if (history.length > 20) history = history.slice(-20);
    })
    .catch(function () {
      typEl.remove();
      addMsg(T.error, 'assistant');
    })
    .finally(function () {
      isSending = false;
      sendEl.disabled = false;
      inputEl.focus();
    });
  }

  /* ---- events ---- */
  btn.addEventListener('click', function () { panelOpen ? closePanel() : openPanel(); });
  document.getElementById('bzw-x').addEventListener('click', closePanel);
  sendEl.addEventListener('click', send);
  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });

}());
