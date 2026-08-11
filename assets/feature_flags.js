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

// FREE_ACCESS_MODE: site-wide "everything free while we test visitor interest"
// switch (2026-08-10). When true, every subscription paywall treats any signed-in
// user as fully entitled — login is still required, only the billing check is
// bypassed. Covers dashboard.html/_cn tool-card locks, index_news(.html/_cn) and
// market_news(.html/_cn) redirect-to-billing gates, index(.html/_cn)'s hpViewAll
// gate modal, login(.html/_cn)'s post-login redirect, baizora_main_form(.html/_cn)'s
// own subscription check, index(.html/_cn)'s "Start Free"->"Sign Up Free" CTA swap
// (below), and the "Free Tier"->"Top Movers" rename (also below). ALL of it is
// driven by this one boolean — every page's HTML keeps its original "Free Tier" /
// paid-flow copy as the literal source, and this file rewrites it at load time
// when the flag is on. Flip to `false` and push to restore the original site
// exactly — no other file needs touching. Does NOT touch account.html/billing.html,
// which keep showing each user's real Stripe status.
window.FREE_ACCESS_MODE = true;

// Generic "Free Tier" -> "Top Movers" (CN: "免费版" -> "涨幅榜") text rename, applied
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
          .replace(/Free Tier\s*·\s*Top Movers/g, 'Top Movers')
          .replace(/the Free Tier/g, 'Top Movers')
          .replace(/Free Tier/g, 'Top Movers')
          .replace(/免费版/g, '涨幅榜');
      }
    }
  });
}
