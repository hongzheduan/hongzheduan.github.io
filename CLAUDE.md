# Baizora — Claude Code Project Context

## What is Baizora
US large-cap equity (S&P 500 + Nasdaq-100) price & volume analytics platform.
Dark navy theme. Bilingual: English + Simplified Chinese.
Live at: `hongzheduan.github.io` (GitHub Pages)
Backend: Firebase (auth) + Stripe (billing) + Cloud Functions (API)
API base: `https://us-central1-baizora.cloudfunctions.net/api/`

---

## File Structure

```
/                          ← root (deployed via GitHub Pages)
├── index.html             ← EN homepage
├── index_cn.html          ← CN homepage
├── login.html / login_cn.html
├── signup.html / signup_cn.html
├── billing.html / billing_cn.html
├── pricing.html / pricing_cn.html
├── dashboard.html / dashboard_cn.html
├── account.html / account_cn.html
├── baizora_main_form.html         ← full authenticated dashboard (EN)
├── baizora_main_form_cn.html      ← full authenticated dashboard (CN)
├── baizora_main_form_free.html    ← free preview (EN, 3 rows, no login)
├── baizora_main_form_free_cn.html ← free preview (CN)
├── firebase.js                    ← Firebase config (shared)
├── data/latest.json               ← daily scanner output
├── assets/
│   ├── about.html / about_cn.html
│   ├── faq.html / faq_cn.html
│   ├── privacy.html / privacy_cn.html
│   ├── terms.html / terms_cn.html
│   ├── disclaimer.html / disclaimer_cn.html
│   ├── baize_favicon_v2.png
│   └── baize_logo_v2.png
└── baizora_index.js               ← Firebase Cloud Functions backend
```

---

## CSS Design System

### Variables (all files)
```css
:root {
  --navy: #060d1f;           /* page background */
  --navy-mid: #0d1e3d;
  --navy-light: #162847;
  --electric: #3b82f6;       /* primary blue */
  --electric-bright: #60a5fa; /* accent blue (same as "ora" in logo) */
  --gold: #f59e0b;
  --gold-light: #fcd34d;
  --green: #22c55e;
  --red: #ef4444;
  --white: #ffffff;          /* pure white for text */
  --muted: #cbd5e1;          /* secondary text */
  --border: rgba(255,255,255,0.09);
}
```

### Text color hierarchy
- Primary text: `#ffffff` (pure white)
- Secondary/muted: `#cbd5e1` (--muted)
- Dim labels: `#94a3b8`
- Very dim: `#64748b`
- Near-invisible (avoid): `#475569`, `#334155`

### Fonts
- `DM Serif Display` — headings, titles, logo
- `DM Mono` — monospace labels, column headers, badges
- `DM Sans` — body, buttons, UI

### Buttons
- `.btn-gold` — gradient orange/amber, primary CTA
- `.btn-primary` — electric blue
- `.btn-secondary` — transparent with border
- `.nav-btn` — small nav buttons
- `.nav-btn-primary` — highlighted nav button

---

## Branding Rules

### Logo image
- File: `assets/baize_favicon_v2.png` — used on ALL pages
- Height: `36px` on all pages (mobile responsive overrides may reduce to 28–32px)

### EN logo
```html
<a href="./" class="logo-wrap">
  <img src="assets/baize_favicon_v2.png" alt="Baizora">
  <span class="logo-text" style="font-family:'DM Serif Display',serif;font-size:20px;color:#f8fafc;letter-spacing:-0.02em;">Baiz<span style="color:#3b82f6;">ora</span></span>
</a>
```

### CN logo (贝佐拉 — ALWAYS use this in all CN pages)
```html
<a href="./" class="logo-wrap">
  <img src="assets/baize_favicon_v2.png" alt="Baizora">
  <span class="brand-cn">贝佐拉</span>
</a>
```
With CSS:
```css
.brand-cn {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 4px;
  background: linear-gradient(90deg, var(--white), var(--electric-bright));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
```

---

## CN Page Rules

1. **ALL links in `_cn.html` files point to `_cn.html` versions** — no exceptions
   - `login.html` → `login_cn.html`
   - `billing.html` → `billing_cn.html`
   - `assets/faq.html` → `assets/faq_cn.html`
   - etc.
2. **Logo**: always `贝佐拉` with `.brand-cn` class
3. **English nav link**: points back to `index.html` (not `index_cn.html`)
4. **Auth JS**: redirect to `_cn.html` pages, button labels in Chinese

---

## Firebase Config
```js
firebase.initializeApp({
  apiKey: "AIzaSyDVX4hPWgY_JK3VyXDjZapeki6Mm-tvw80",
  authDomain: "baizora.firebaseapp.com",
  projectId: "baizora"
});
```

### Stripe Price IDs
- Monthly: `price_1TSJVFDRVR8GgjbGyMDrFqTr`
- Yearly: `price_1TSIPMDRVR8GgjbGDyrT5E3C`

---

## Dashboard Column Names

### EN (baizora_main_form.html)
| Data Key | Column Header |
|---|---|
| Ticker | TICKER |
| Spark1Y | 1Y TREND |
| Price | PRICE |
| VolumeM | VOL(M) |
| PriceChange1D | 1D P CHG% |
| PriceVsMA21_1D | PRICE/MA21 |
| VolumeChange1D | 1D V CHG% |
| VolumeVsMA21_1D | VOL/MA21 |
| ${w}PriceChange | P CHG% |
| ${w}MaxPriceChange | MAX P CHG% |
| ${w}MaxPriceChangeDay | MAX P% Day |
| ${w}VolumeChangeAtMaxPrice | V@P Day |
| ${w}MaxVolumeChange | MAX V CHG% |
| ${w}MaxVolumeChangeDay | MAX V% Day |
| ${w}PriceChangeAtMaxVolume | P@V Day |

### CN (baizora_main_form_cn.html)
| Data Key | Column Header |
|---|---|
| Ticker | 代码 |
| Spark1Y | 年趋势线 |
| Price | 价格 |
| VolumeM | 成交量(M) |
| PriceChange1D | 日价格变化 |
| PriceVsMA21_1D | 价格/MA21 |
| VolumeChange1D | 日成交量变化 |
| VolumeVsMA21_1D | 量/MA21 |
| ${w}PriceChange | 总涨幅 |
| ${w}MaxPriceChange | 日最大价涨 |
| ${w}MaxPriceChangeDay | 最大价涨日 |
| ${w}VolumeChangeAtMaxPrice | 量@价日 |
| ${w}MaxVolumeChange | 日最大量涨 |
| ${w}MaxVolumeChangeDay | 最大量涨日 |
| ${w}PriceChangeAtMaxVolume | 价@量日 |

### Timeframe windows
EN: `1D / 2W / 1M / 3M / 6M / 9M / 1Y`
CN: `1天 / 2周 / 1月 / 3月 / 6月 / 9月 / 1年`

---

## Auth Pattern (all pages)

```js
firebase.auth().onAuthStateChanged(function(user) {
  const btn = document.getElementById('navLoginLogout');
  const dashBtn = document.getElementById('navDashBtn');
  const emailEl = document.getElementById('navUserEmail');
  const regBtn = document.getElementById('navRegisterBtn'); // hide when logged in

  if (user) {
    // Show dashboard link, hide register/login
    dashBtn.style.display = 'inline-flex';
    emailEl.textContent = user.email;
    emailEl.style.display = 'inline';
    if (regBtn) regBtn.style.display = 'none';
    btn.textContent = 'Sign Out'; // or '退出登录' in CN
    btn.href = '#';
    btn.onclick = (e) => { e.preventDefault(); doLogout(); };
  } else {
    dashBtn.style.display = 'none';
    emailEl.style.display = 'none';
    if (regBtn) regBtn.style.display = 'inline-block';
    btn.textContent = 'Sign In'; // or '登录' in CN
    btn.href = 'login.html'; // or 'login_cn.html' in CN
  }
});

async function doLogout() {
  await firebase.auth().signOut();
  window.location.href = 'index.html'; // or 'index_cn.html' in CN
}
```

### Mobile email: hide on mobile
```css
@media (max-width: 768px) {
  #userEmail { display: none !important; }
  #headerEmail { display: none !important; }
}
```

---

## Key UI Patterns

### Eyebrow badge
```html
<div class="hero-eyebrow">◈ &nbsp; Text here</div>
```

### Section label
```html
<div class="section-label">LABEL TEXT</div>
```

### Card style
```css
background: rgba(13, 30, 61, 0.6);
border: 1px solid var(--border);
border-radius: 16px;
```

### Announcement bar
```css
background: linear-gradient(90deg, #7c2d12, #92400e, #7c2d12);
color: var(--gold-light);
```

---

## Common CN Translations Reference

| EN | CN |
|---|---|
| Sign In | 登录 |
| Sign Out | 退出登录 |
| Register for Free | 免费注册 |
| Dashboard | 个人主页 |
| My Account | 我的账户 |
| Plans | 价格方案 |
| About | 平台简介 |
| Home | 首页 |
| Free Preview | 免费预览 |
| Privacy | 隐私政策 |
| Terms | 服务条款 |
| Disclaimer | 免责声明 |
| FAQ | 常见问题 |
| Monthly | 月付 |
| Yearly | 年付 |
| Start Free Trial | 开始免费试用 |
| Cancel anytime | 随时可取消 |
| Loading… | 加载中… |
| Back to Home | 返回首页 |

---

## GitHub Actions Scanner
- File: `scanner.yml`
- Schedule: `cron: "30 20 * * 1-5"` (weekdays, 8:30 PM UTC = after US market close)
- Output: `data/latest.json` + `archive/*.csv`
- Uses `git stash/rebase/pop` to avoid conflicts

---

## Pricing
- Monthly: $9.99/month
- Yearly: $99/year (~$8.25/month, ~17% savings)
- 7-day free trial for new subscribers (once per email)
- Payments via Stripe Customer Portal
- Contact: support@baizora.com
