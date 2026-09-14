// Cost-control switch for Baizora's paid-tier-only features (no paying customers yet,
// 2026-08). Flip to `true` and push when we have paying customers again — no other
// file needs touching. Loaded before each dashboard/stock page's main script.
//
// BAIZORA_LIVE_PRICES: gates intraday price polling during market hours (the
// /iex-quotes Cloud Function, Tiingo-backed) across baizora_main_form(.html/_cn/_free/
// _free_cn), stocks/*.html, top-price-movers.html, and unusual-volume.html. When
// false, those pages show the scanner's last-close price with a static "as of {date}
// close" label instead of live-updating.
window.BAIZORA_LIVE_PRICES = false;

// BAIZORA_PRIVATE_MODE: "private site" lockdown (2026-09-08), added to reduce
// Yahoo Finance ToS exposure while price/volume data comes from free yfinance
// (see assets/revert_yfinance_switch_checklist.html). When true, pages that
// previously showed scanner data with NO login now redirect signed-out visitors
// to login.html: baizora_main_form_freetier(.html/_cn), top-price-movers.html,
// unusual-volume.html, all stocks/*.html, and (2026-09-14) the homepage
// index(.html/_cn) itself. Each gate is written as
// `if (window.BAIZORA_PRIVATE_MODE && !user) { location.replace('login.html') }`,
// so flipping this to `false` and pushing re-opens all of them — no other file
// needs touching. Pages that were already login-only (dashboard, baizora_main_form,
// account, billing, chart_archive, index_news, market_news, market_heatmap) are
// unaffected either way.
// 2026-09-14: also closes public account creation — reason: still no real signups
// and the site keeps changing fast enough that a stray new account would just be
// stale; reopen when ready to go public again. login(.html/_cn) hide their
// "Create one"/"免费注册" link (`.signup-row`), and signup(.html/_cn) unconditionally
// redirect to login (even a signed-in user gets bounced — no reason to reach the
// signup form at all while this is on) so the direct URL isn't a bypass. Existing
// accounts are completely unaffected — this only blocks *new* signups, any already-
// registered user (owner + the 2 current outside users) still signs in normally.
// Pair the revert with restoring robots.txt (git history) when going public again.
window.BAIZORA_PRIVATE_MODE = true;

// FREE_ACCESS_MODE: site-wide "everything free while we test visitor interest"
// switch (2026-08-10). When true, every subscription paywall treats any signed-in
// user as fully entitled — login is still required, only the billing check is
// bypassed. Covers dashboard.html/_cn tool-card locks, index_news(.html/_cn) and
// market_news(.html/_cn) redirect-to-billing gates, index(.html/_cn)'s hpViewAll
// gate modal, login(.html/_cn)'s post-login redirect, baizora_main_form(.html/_cn)'s
// own subscription check, index(.html/_cn)'s "Start Free"->"Sign Up Free" CTA swap
// (below), and the "Free Tier"->"Preview" rename (also below). ALL of it is
// driven by this one boolean — every page's HTML keeps its original "Free Tier" /
// paid-flow copy as the literal source, and this file rewrites it at load time
// when the flag is on. Flip to `false` and push to restore the original site
// exactly — no other file needs touching. Does NOT touch account.html/billing.html,
// which keep showing each user's real Stripe status.
window.FREE_ACCESS_MODE = true;

// Generic "Free Tier" -> "Preview" (CN: "免费版" -> "预览") text rename, applied
// to every text node on any page that loads this file, while FREE_ACCESS_MODE is on.
// Runs once on DOMContentLoaded. Skips <script>/<style> contents. New pages that link
// to baizora_main_form_freetier(.html/_cn) automatically get the rename for free —
// no per-page wiring needed, and nothing to revert per-page when the flag flips back.
if (window.FREE_ACCESS_MODE) {
  document.addEventListener('DOMContentLoaded', function () {
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        var tag = node.parentNode && node.parentNode.nodeName;
        return (tag === 'SCRIPT' || tag === 'STYLE') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      }
    });
    var node;
    while ((node = walker.nextNode())) {
      if (/Free Tier|免费版/.test(node.nodeValue)) {
        node.nodeValue = node.nodeValue
          .replace(/Free Tier\s*·\s*Top Movers/g, 'Preview')
          .replace(/the Free Tier/g, 'Preview')
          .replace(/Free Tier/g, 'Preview')
          .replace(/免费版/g, '预览');
      }
    }
  });
}
