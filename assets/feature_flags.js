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
