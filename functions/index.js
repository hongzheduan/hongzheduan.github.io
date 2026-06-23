const functions = require("firebase-functions");
const { onRequest } = require("firebase-functions/v2/https");
const express = require("express");
const Stripe = require("stripe");
const admin = require("firebase-admin");
const cors = require("cors");
const https = require("https");
const AnthropicModule = require("@anthropic-ai/sdk");
const Anthropic = AnthropicModule.default || AnthropicModule;

const { defineSecret } = require("firebase-functions/params");

admin.initializeApp();

const app = express();

/* ---------------------------
   SECRETS
--------------------------- */
const stripeSecret = defineSecret("STRIPE_SECRET_KEY");
const stripeWebhookSecret = defineSecret("STRIPE_WEBHOOK_SECRET");
const anthropicKey = defineSecret("ANTHROPIC_API_KEY");

/* ---------------------------
   MIDDLEWARE
   NOTE: express.json() is NOT global — webhook needs raw bytes.
   Each route gets json() explicitly.
--------------------------- */
app.use(cors({ origin: true }));

/* ---------------------------
   IEX LIVE QUOTES  (homepage, movers, volume pages)
   Accepts optional ?tickers=A,B,C param; defaults to 10 homepage tickers.
   60s in-memory cache keyed by sorted ticker list — limits Tiingo calls to
   ~1,440/day per unique ticker set regardless of visitor count.
--------------------------- */
const _IEX_DEFAULT = "NVDA,GOOGL,AAPL,MSFT,AMZN,AVGO,TSLA,META,WMT,MU";
const _iexCacheMap = new Map(); // key: sorted-ticker-string → {data, ts}

function _tiingoGet(url) {
  return new Promise((resolve, reject) => {
    https.get(url, res => {
      let body = "";
      res.on("data", c => body += c);
      res.on("end", () => { try { resolve(JSON.parse(body)); } catch(e) { reject(e); } });
    }).on("error", reject);
  });
}

app.get("/iex-quotes", async (req, res) => {
  const raw  = ((req.query.tickers || _IEX_DEFAULT) + "").toUpperCase();
  const list = raw.split(",").map(t => t.trim()).filter(Boolean);
  const key  = [...list].sort().join(",");
  try {
    const now = Date.now();
    const cached = _iexCacheMap.get(key);
    if (cached && (now - cached.ts) < 10_000) return res.json(cached.data);

    // Evict entries older than 30 seconds to keep the map small
    for (const [k, v] of _iexCacheMap) {
      if (now - v.ts > 30_000) _iexCacheMap.delete(k);
    }

    const data = await _tiingoGet(
      `https://api.tiingo.com/iex/?tickers=${list.join(",")}&token=${process.env.TIINGO_API_KEY}`
    );
    if (!Array.isArray(data)) {
      console.error("iex-quotes: unexpected Tiingo response:", JSON.stringify(data).substring(0, 300));
    }
    const result = {};
    (Array.isArray(data) ? data : []).forEach(q => {
      const t = (q.ticker || "").toUpperCase();
      if (!t) return;
      const last = q.tngoLast ?? q.last;
      const prev = q.prevClose;
      result[t] = {
        last,
        chgPct: (prev && last) ? +((last - prev) / prev * 100).toFixed(2) : null,
        open:   q.open   ?? null,
        high:   q.high   ?? null,
        low:    q.low    ?? null,
        volume: q.volume ?? null,
        ts:     q.lastSaleTimestamp ?? q.quoteTimestamp ?? null,
      };
    });
    _iexCacheMap.set(key, { data: result, ts: now });
    res.json(result);
  } catch(e) {
    console.error("iex-quotes:", e.message);
    const cached = _iexCacheMap.get(key);
    res.status(200).json(cached ? cached.data : {});
  }
});

/* ---------------------------
   INDEX MEMBERSHIP NEWS
   Fetches Google News RSS for S&P 500 + Nasdaq-100 membership changes.
   1-hour in-memory cache — Google RSS is only called once per hour
   regardless of how many users load the page.
--------------------------- */
const _NEWS_QUERIES = [
  { key: "S&P 500 addition",    query: '"added to S&P 500" OR "will join S&P 500" OR "joins S&P 500" OR "joining S&P 500" OR "entering S&P 500" OR "S&P 500 index addition" OR "S&P 500 inclusion"' },
  { key: "S&P 500 removal",     query: '"removed from S&P 500" OR "dropped from S&P 500" OR "leaving S&P 500" OR "exits S&P 500" OR "S&P 500 index removal" OR "S&P 500 exclusion"' },
  { key: "Nasdaq-100 addition", query: '"added to Nasdaq-100" OR "will join Nasdaq-100" OR "joins Nasdaq-100" OR "joining Nasdaq-100" OR "entering Nasdaq-100" OR "Nasdaq-100 index addition" OR "Nasdaq-100 inclusion"' },
  { key: "Nasdaq-100 removal",  query: '"removed from Nasdaq-100" OR "dropped from Nasdaq-100" OR "leaving Nasdaq-100" OR "exits Nasdaq-100" OR "Nasdaq-100 index removal" OR "Nasdaq-100 exclusion"' },
];

const _NEWS_SKIP = [
  "within a year", "within a month", "within months",
  "since joining", "since being added", "since addition",
  "year after joining", "months after joining", "a year of joining",
  "years after", "year later", "months later", "one year", "look back",
];

let _newsCache = { data: null, ts: 0 };
const _NEWS_TTL = 60 * 60 * 1000; // 1 hour

function _decodeXmlEntities(str) {
  return str.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
}

function _parseRssItems(xml) {
  const items = [];
  const itemRe = /<item>([\s\S]*?)<\/item>/g;
  let m;
  while ((m = itemRe.exec(xml)) !== null) {
    const block = m[1];
    const title   = _decodeXmlEntities(((block.match(/<title><!\[CDATA\[([\s\S]*?)\]\]><\/title>/) ||
                      block.match(/<title>([\s\S]*?)<\/title>/)) || [])[1] || "");
    const link    = (block.match(/<link>([\s\S]*?)<\/link>/)     || [])[1] || "";
    const pubDate = (block.match(/<pubDate>([\s\S]*?)<\/pubDate>/) || [])[1] || "";
    const source  = _decodeXmlEntities(((block.match(/<source[^>]*>([\s\S]*?)<\/source>/) ||
                      block.match(/<source>([\s\S]*?)<\/source>/)) || [])[1] || "");
    if (title && link) items.push({ title: title.trim(), link: link.trim(), pubDate: pubDate.trim(), source: source.trim() });
  }
  return items;
}

async function _translateToZh(text) {
  try {
    const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q=${encodeURIComponent(text)}`;
    const resp = await fetch(url, { signal: AbortSignal.timeout(8000) });
    const data = await resp.json();
    return data[0].map(p => p[0]).join("");
  } catch(e) {
    return "";
  }
}

app.get("/index-news", async (req, res) => {
  try {
    const now = Date.now();
    if (_newsCache.data && (now - _newsCache.ts) < _NEWS_TTL) {
      return res.json(_newsCache.data);
    }

    const cutoff = new Date(now - 90 * 24 * 60 * 60 * 1000);
    const allItems = [];

    for (const { key, query } of _NEWS_QUERIES) {
      try {
        const url = `https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=en-US&gl=US&ceid=US:en`;
        const resp = await fetch(url, {
          headers: { "User-Agent": "Mozilla/5.0 (compatible; Baizora/1.0)" },
          signal: AbortSignal.timeout(10000),
        });
        const xml = await resp.text();
        for (const it of _parseRssItems(xml)) {
          const pubDt = new Date(it.pubDate);
          if (isNaN(pubDt) || pubDt < cutoff) continue;
          const tl = it.title.toLowerCase();
          if (_NEWS_SKIP.some(p => tl.includes(p))) continue;
          allItems.push({ category: key, date: pubDt.toISOString().slice(0, 10), title: it.title, source: it.source, link: it.link });
        }
      } catch(e) {
        console.warn(`[index-news] ${key}:`, e.message);
      }
    }

    allItems.sort((a, b) => b.date.localeCompare(a.date));

    // Deduplicate by title
    const seen = new Set();
    const deduped = allItems.filter(it => { const suffix = " - " + it.source; const base = it.title.endsWith(suffix) ? it.title.slice(0, -suffix.length) : it.title; const k = base.toLowerCase().replace(/\s+/g, " ").trim(); if (seen.has(k)) return false; seen.add(k); return true; });

    // Translate titles to Chinese (cached for 1 hour so latency only hits once)
    for (const item of deduped) {
      const suffix = " - " + item.source;
      const clean = item.title.endsWith(suffix) ? item.title.slice(0, -suffix.length) : item.title;
      item.title_cn = await _translateToZh(clean);
      await new Promise(r => setTimeout(r, 100));
    }

    // If fresh fetch returned nothing, serve stale cache rather than empty results
    if (deduped.length === 0 && _newsCache.data && _newsCache.data.items.length > 0) {
      return res.json(_newsCache.data);
    }

    const result = {
      fetched: new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date()).replace(", ", " ") + " ET",
      lookback_days: 90,
      items: deduped,
    };

    _newsCache = { data: result, ts: now };
    res.json(result);
  } catch(e) {
    console.error("index-news:", e.message);
    if (_newsCache.data) return res.json(_newsCache.data);
    res.status(500).json({ error: "Failed to fetch news" });
  }
});

/* ---------------------------
   MARKET NEWS
   General financial headlines from Google News RSS.
   1-hour in-memory cache.
--------------------------- */
let _marketNewsCache = { en: { data: null, ts: 0 }, zh: { data: null, ts: 0 } };
const _MARKET_NEWS_TTL = 60 * 60 * 1000;
const _MARKET_NEWS_QUERY = 'stock market OR "Federal Reserve" OR earnings OR war OR tariff OR inflation';
const _MARKET_NEWS_QUERY_ZH = '股市 OR 利率 OR 美联储 OR 财报 OR 美股 OR 关税 OR 油价 OR 失业率 OR 通胀';

app.get("/market-news", async (req, res) => {
  const lang = req.query.lang === "zh" ? "zh" : "en";
  try {
    const cache = _marketNewsCache[lang];
    const now = Date.now();
    if (cache.data && (now - cache.ts) < _MARKET_NEWS_TTL) {
      return res.json(cache.data);
    }
    const [hl, gl, ceid, query] = lang === "zh"
      ? ["zh-CN", "CN", "CN:zh-Hans", _MARKET_NEWS_QUERY_ZH]
      : ["en-US", "US", "US:en", _MARKET_NEWS_QUERY];
    const url = `https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=${hl}&gl=${gl}&ceid=${ceid}`;
    const resp = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36" },
      signal: AbortSignal.timeout(10000),
    });
    const xml = await resp.text();
    if (!xml.includes("<item>")) console.warn("market-news: 0 items from Google RSS. status:", resp.status, "preview:", xml.slice(0, 200));
    const parsed = _parseRssItems(xml);
    const items = parsed.slice(0, 6).map(it => ({
      title: it.title,
      source: it.source,
      link: it.link,
      date: new Date(it.pubDate).toISOString().slice(0, 10),
    }));
    const fetched_et = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: true,
    }).format(new Date()) + " ET";
    const result = { fetched: fetched_et, items };
    if (items.length > 0) _marketNewsCache[lang] = { data: result, ts: now };
    else if (_marketNewsCache[lang].data) return res.json(_marketNewsCache[lang].data);
    res.json(result);
  } catch(e) {
    console.error("market-news:", e.message);
    const stale = _marketNewsCache[lang];
    if (stale && stale.data) return res.json(stale.data);
    res.status(500).json({ error: "Failed to fetch news" });
  }
});

/* ---------------------------
   STRIPE INIT
--------------------------- */
function getStripe() {
  return new Stripe(stripeSecret.value());
}

/* ---------------------------
   HELPER: find or create Stripe customer by email
--------------------------- */
async function findOrCreateCustomer(stripe, email) {
  const existing = await stripe.customers.list({ email, limit: 1 });
  if (existing.data.length > 0) return existing.data[0].id;
  const customer = await stripe.customers.create({ email });
  return customer.id;
}

/* ---------------------------
   HELPER: check if customer has active/trialing sub
--------------------------- */
async function getActiveSubscription(stripe, customerId) {
  const subs = await stripe.subscriptions.list({
    customer: customerId,
    status: "all",
    limit: 10,
  });
  return subs.data.find(s => s.status === "active" || s.status === "trialing") || null;
}

/* ---------------------------
   HEALTH CHECK
--------------------------- */
app.get("/", async (req, res) => {
  try {
    const stripe = getStripe();
    await stripe.balance.retrieve();
    res.json({ ok: true, message: "Stripe Connected" });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

/* ---------------------------
   CHECKOUT
--------------------------- */
const MONTHLY = "price_1TSJVFDRVR8GgjbGyMDrFqTr";
const YEARLY  = "price_1TSIPMDRVR8GgjbGDyrT5E3C";

async function createCheckout(priceId, email, res) {
  try {
    if (!email) return res.status(400).json({ error: "Missing email" });

    const stripe = getStripe();
    const customerId = await findOrCreateCustomer(stripe, email);

    // Block if already subscribed
    const existingSub = await getActiveSubscription(stripe, customerId);
    if (existingSub) {
      return res.status(409).json({
        error: "already_subscribed",
        message: "您已有有效订阅，无需重复订阅。",
        status: existingSub.status,
      });
    }

    // One trial per email ever
    const allSubs = await stripe.subscriptions.list({ customer: customerId, status: "all", limit: 20 });
    const hadTrialBefore = allSubs.data.some(s => s.trial_start != null);

    // Block trial if a saved card fingerprint was already used for a trial
    if (!hadTrialBefore) {
      const paymentMethods = await stripe.paymentMethods.list({ customer: customerId, type: "card" });
      for (const pm of paymentMethods.data) {
        if (pm.card && pm.card.fingerprint) {
          const fpSnap = await admin.firestore()
            .collection("usedTrialCards")
            .where("fingerprint", "==", pm.card.fingerprint)
            .limit(1)
            .get();
          if (!fpSnap.empty) {
            return res.status(409).json({ error: "This card has already been used for a free trial." });
          }
        }
      }
    }

    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      customer: customerId,
      subscription_data: hadTrialBefore ? {} : { trial_period_days: 7 },
      success_url: "https://baizora.com/dashboard.html",
      cancel_url:  "https://baizora.com/billing.html",
    });

    res.json({ url: session.url });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}

app.post("/create-monthly", express.json(), (req, res) => createCheckout(MONTHLY, req.body.email, res));
app.post("/create-yearly",  express.json(), (req, res) => createCheckout(YEARLY,  req.body.email, res));

/* ---------------------------
   WEBHOOK
--------------------------- */
app.post("/webhook", async (req, res) => {
  const stripe = getStripe();
  const sig = req.headers["stripe-signature"];

  let event;
  try {
    let rawBody = req.rawBody;
    if (!rawBody) rawBody = JSON.stringify(req.body);
    event = stripe.webhooks.constructEvent(rawBody, sig, stripeWebhookSecret.value());
  } catch (err) {
    console.error("Webhook signature error:", err.message);
    return res.status(400).send(err.message);
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object;
    try {
      if (!session.subscription) {
        console.log("No subscription in session, skipping.");
        return res.json({ received: true });
      }
      const customer     = await stripe.customers.retrieve(session.customer);
      const subscription = await stripe.subscriptions.retrieve(session.subscription);
      await admin.firestore()
        .collection("subscriptions")
        .doc(session.subscription)
        .set({
          email:             customer.email || "",
          customerId:        session.customer,
          subscriptionId:    session.subscription,
          status:            subscription.status,
          cancelAtPeriodEnd: subscription.cancel_at_period_end || false,
          currentPeriodEnd:  subscription.current_period_end || subscription.trial_end || 0,
          createdAt:         admin.firestore.FieldValue.serverTimestamp(),
        });
      console.log("Subscription written:", session.subscription, subscription.status);

      // Save card fingerprint for trial subscriptions to prevent reuse across accounts
      if (subscription.trial_start != null) {
        const pmId = subscription.default_payment_method;
        if (pmId) {
          try {
            const pm = await stripe.paymentMethods.retrieve(pmId);
            if (pm.card && pm.card.fingerprint) {
              await admin.firestore()
                .collection("usedTrialCards")
                .add({
                  fingerprint: pm.card.fingerprint,
                  email:       customer.email || "",
                  createdAt:   admin.firestore.FieldValue.serverTimestamp(),
                });
              console.log("Saved trial card fingerprint:", pm.card.fingerprint);
            }
          } catch (fpErr) {
            console.error("Failed to save card fingerprint:", fpErr.message);
          }
        }
      }
    } catch (e) {
      console.error("checkout.session.completed error:", e.message);
      return res.json({ received: true, warning: e.message });
    }
  }

  if (event.type === "customer.subscription.updated") {
    const sub = event.data.object;
    try {
      const customer = await stripe.customers.retrieve(sub.customer);
      await admin.firestore()
        .collection("subscriptions")
        .doc(sub.id)
        .set({
          email:             customer.email || "",
          customerId:        sub.customer,
          subscriptionId:    sub.id,
          status:            sub.status,
          cancelAtPeriodEnd: sub.cancel_at_period_end,
          currentPeriodEnd:  sub.current_period_end,
        }, { merge: true });
    } catch(e) {
      console.error("subscription.updated error:", e.message);
    }
  }

  if (event.type === "customer.subscription.deleted") {
    const sub = event.data.object;
    try {
      await admin.firestore()
        .collection("subscriptions")
        .doc(sub.id)
        .set({
          status:            "canceled",
          cancelAtPeriodEnd: false,
          canceledAt:        admin.firestore.FieldValue.serverTimestamp(),
        }, { merge: true });
    } catch(e) {
      console.error("subscription.deleted error:", e.message);
    }
  }

  res.json({ received: true });
});

/* ---------------------------
   GET USER
--------------------------- */
app.get("/get-user", async (req, res) => {
  try {
    const uid = req.query.uid;
    if (!uid) return res.status(400).json({ error: "Missing uid" });

    const userRecord = await admin.auth().getUser(uid);
    const email = userRecord.email;
    if (!email) return res.status(404).json({ error: "No email found" });

    // 1. Check new subscriptions collection
    const snapshot = await admin.firestore()
      .collection("subscriptions")
      .where("email", "==", email)
      .where("status", "in", ["trialing", "active"])
      .limit(1)
      .get();

    if (!snapshot.empty) {
      const sub = snapshot.docs[0].data();
      return res.json({
        subscriptionStatus: sub.status,
        cancelAtPeriodEnd:  sub.cancelAtPeriodEnd,
        currentPeriodEnd:   sub.currentPeriodEnd,
      });
    }

    // 2. Check old users collection (keyed by UID)
    const userDoc = await admin.firestore().collection("users").doc(uid).get();
    if (userDoc.exists) {
      const userData = userDoc.data();
      const oldStatus = userData.subscriptionStatus || "inactive";
      if (oldStatus === "active" || oldStatus === "trialing") {
        if (userData.stripeSubscriptionId) {
          try {
            const stripe = getStripe();
            const sub = await stripe.subscriptions.retrieve(userData.stripeSubscriptionId);
            await admin.firestore().collection("subscriptions").doc(sub.id).set({
              email,
              customerId:        sub.customer,
              subscriptionId:    sub.id,
              status:            sub.status,
              cancelAtPeriodEnd: sub.cancel_at_period_end,
              currentPeriodEnd:  sub.current_period_end,
              createdAt:         admin.firestore.FieldValue.serverTimestamp(),
            }, { merge: true });
            return res.json({
              subscriptionStatus: sub.status,
              cancelAtPeriodEnd:  sub.cancel_at_period_end,
              currentPeriodEnd:   sub.current_period_end,
            });
          } catch(e) {
            console.warn("Stripe sub lookup failed:", e.message);
          }
        }
        return res.json({ subscriptionStatus: oldStatus });
      }
    }

    // 3. Stripe fallback — search all customers for this email
    const stripe = getStripe();
    const customers = await stripe.customers.list({ email, limit: 10 });
    let activeSub = null;
    let foundCustomerId = null;

    for (const customer of customers.data) {
      const sub = await getActiveSubscription(stripe, customer.id);
      if (sub) { activeSub = sub; foundCustomerId = customer.id; break; }
    }

    if (activeSub) {
      await admin.firestore().collection("subscriptions").doc(activeSub.id).set({
        email,
        customerId:        foundCustomerId,
        subscriptionId:    activeSub.id,
        status:            activeSub.status,
        cancelAtPeriodEnd: activeSub.cancel_at_period_end,
        currentPeriodEnd:  activeSub.current_period_end,
        createdAt:         admin.firestore.FieldValue.serverTimestamp(),
      }, { merge: true });
      return res.json({
        subscriptionStatus: activeSub.status,
        cancelAtPeriodEnd:  activeSub.cancel_at_period_end,
        currentPeriodEnd:   activeSub.current_period_end,
      });
    }

    return res.json({ subscriptionStatus: "inactive" });

  } catch (e) {
    console.error(e);
    res.status(500).json({ error: e.message });
  }
});

/* ---------------------------
   PORTAL
--------------------------- */
app.post("/create-portal", express.json(), async (req, res) => {
  try {
    const stripe = getStripe();
    const { uid } = req.body;
    if (!uid) return res.status(400).json({ error: "Missing uid" });

    const userRecord = await admin.auth().getUser(uid);
    const email = userRecord.email;
    if (!email) return res.status(404).json({ error: "No email found" });

    const customerId = await findOrCreateCustomer(stripe, email);
    const portalSession = await stripe.billingPortal.sessions.create({
      customer:   customerId,
      return_url: "https://baizora.com/dashboard.html",
    });

    res.json({ url: portalSession.url });
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: e.message });
  }
});

/* ---------------------------
   CANCEL SUBSCRIPTION
--------------------------- */
app.post("/cancel-subscription", express.json(), async (req, res) => {
  try {
    const stripe = getStripe();
    const { uid } = req.body;
    if (!uid) return res.status(400).json({ error: "Missing uid" });

    const userRecord = await admin.auth().getUser(uid);
    const email = userRecord.email;

    let subscriptionId = null;
    let firestoreRef = null;

    // 1. Check new subscriptions collection
    const snapshot = await admin.firestore()
      .collection("subscriptions")
      .where("email", "==", email)
      .where("status", "in", ["trialing", "active"])
      .limit(1)
      .get();

    if (!snapshot.empty) {
      subscriptionId = snapshot.docs[0].data().subscriptionId;
      firestoreRef = snapshot.docs[0].ref;
    }

    // 2. Check old users collection
    if (!subscriptionId) {
      const userDoc = await admin.firestore().collection("users").doc(uid).get();
      if (userDoc.exists) {
        subscriptionId = userDoc.data().stripeSubscriptionId;
      }
    }

    // 3. Stripe fallback
    if (!subscriptionId) {
      const customers = await stripe.customers.list({ email, limit: 10 });
      for (const customer of customers.data) {
        const sub = await getActiveSubscription(stripe, customer.id);
        if (sub) { subscriptionId = sub.id; break; }
      }
    }

    if (!subscriptionId) {
      return res.status(404).json({ error: "No active subscription found" });
    }

    await stripe.subscriptions.update(subscriptionId, { cancel_at_period_end: true });

    // Update Firestore immediately
    if (firestoreRef) {
      await firestoreRef.set({ cancelAtPeriodEnd: true }, { merge: true });
    }

    res.json({ success: true });
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: e.message });
  }
});

/* ---------------------------
   CHAT (AI Assistant)
--------------------------- */
const CHAT_SYSTEM_EN = `You are a helpful, friendly support assistant for Baizora, a US large-cap equity price & volume analytics platform. Answer questions about Baizora only. Be concise and accurate.

## ABOUT BAIZORA
- Tracks all S&P 500 + Nasdaq-100 constituents (~500+ large-cap US equities)
- Daily data updated after US market close on weekdays (Mon–Fri)
- Dark navy themed web dashboard, bilingual English + Simplified Chinese
- Website: hongzheduan.github.io | Contact: support@baizora.com

## FREE PREVIEW
No login required. Shows the top 3 stocks by daily price increase. Includes live sparklines, multi-timeframe stats, and fundamentals (PE, market cap, EPS, sector). Accessible at baizora.com — a genuine sample of the full product.

## GETTING STARTED / SIGN UP
1. Click "Register for Free" on the homepage
2. Create account with email + password (min 6 chars, at least 1 uppercase + 1 number)
3. A verification email is sent from noreply@baizora.firebaseapp.com — you MUST click the link before logging in (check spam folder if not found)
4. After login: active subscribers go directly to the Dashboard; new/unsubscribed users are taken to the subscription page
5. On the subscription page, choose Monthly or Yearly and complete Stripe checkout — 7-day free trial starts immediately

## PRICING
- Monthly: $9.99/month
- Yearly: $99/year (~$8.25/month, ~17% savings)
- Both plans include identical features — all 500+ symbols, all timeframes, sparklines, fundamentals
- 7-day free trial for first-time subscribers (once per email address AND once per credit card)
- After trial: auto-renews at selected rate
- Cancel anytime — cancellation takes effect at end of current billing period, no further charges
- No refunds on subscription charges — use the free trial to evaluate before committing

## MANAGING SUBSCRIPTION
- Account page: view subscription status, trial end date, cancel button
- "Manage Billing" button opens Stripe Customer Portal: update payment method, view invoices, switch plans, cancel
- Cancellation during trial: no charge, access continues until trial expires

## FREE TRIAL RESTRICTIONS
- One trial per email address — re-subscribing with same email starts paid immediately
- One trial per credit card — a previously used card starts paid immediately regardless of account
- This prevents trial abuse; the policy is enforced at both email and card level

## DATA & UPDATE SCHEDULE
- Scanner runs Mon–Fri after US market close
- Post-market data from provider arrives ~6 PM Eastern Time; dashboard updates 6–7 PM ET
- Occasional delays from data provider are rare but possible — if data looks stale, wait and refresh
- Weekends/holidays: most recent Friday's closing data is shown (normal behavior)
- Price, volume, sparklines, all signals: most recent session's closing data
- EPS, P/E, sector: sourced from SEC EDGAR XBRL filings, refreshed ~weekly (updates when companies file new 10-Q/10-K quarterly reports)
- Baizora reports TTM diluted GAAP EPS — different from "adjusted" or "non-GAAP" figures on other platforms (GAAP includes one-time charges, restructuring costs, write-downs)

## BETA ANALYSIS (INITIAL EOD UPDATE)
- Between 4:00 PM ET (market close) and 6:30–7:00 PM ET (full scan), dashboard auto-runs a client-side "beta" analysis using live EOD data from Tiingo
- Homepage shows: "Analysis (beta) updated: [today's date], full update 6:30–7:00 PM ET"
- Beta updates: Price, 1D P CHG%, Vol(M), 1D V CHG%, Price/MA21, Vol/MA21, today's candlestick bar
- NOT updated in beta: multi-week stats (2W–1Y), scores, sparklines — these need full historical data
- After full scan: homepage shows "Analysis (final) updated: [date]" — all columns refreshed
- Before 4 PM ET on trading days: shows "Analysis updated: [prev date] (current session updates 6:30–7:00 PM ET)"
- Weekends/holidays: no beta label, just shows last scan date

## SPARKLINE MARKERS (1Y TREND column)
- ▲ Triangle = highest-volume day in past year. Green = price was up that day; red = price was down
- ● Circle (with glow) = highest single-day price change in past year. Green = volume was elevated; red = volume was low
- These markers highlight when unusual activity occurred — hover the "1Y Trend" column header in the dashboard for a reminder

## DASHBOARD COLUMNS
Fixed columns:
- TICKER: Stock symbol
- 1Y TREND: 1-year price sparkline with event markers (see above)
- PRICE: Current stock price (USD)
- VOL(M): Daily trading volume in millions
- 1D P CHG%: Today's price change %
- PRICE/MA21: Price deviation from 21-day moving average
- 1D V CHG%: Today's volume change %
- VOL/MA21: Volume deviation from 21-day moving average

Timeframe columns (select 1D / 2W / 1M / 3M / 6M / 9M / 1Y):
- 1D view: today's price/volume changes vs MA21
- All other timeframes show total price change over the period + single largest daily price and volume moves within the window and when they occurred:
  - P CHG%: Total price change for the period
  - MAX P CHG%: Largest single-day price gain in period
  - MAX P% Day: Date of that max gain
  - V@P Day: Volume change % on the max-price day
  - MAX V CHG%: Largest single-day volume surge
  - MAX V% Day: Date of that max volume surge
  - P@V Day: Price change on the max-volume day

## WATCHLIST (STARRED STOCKS)
- Without login: stored in browser local storage — lost if you clear cache/cookies, switch browser/device, or use incognito
- With login: watchlist syncs to the cloud and restores on any signed-in device

## INDEX CONSTITUENT ACCURACY
- Constituent list sourced from a third-party data provider, updated daily after close
- Auto round-trip detection: stocks added then removed within 3 days are treated as data errors
- Treat as a reliable approximation, not an official source — refer to S&P Global or Nasdaq for definitive lists

## IMPORTANT DISCLAIMER
Baizora is a data intelligence platform — it surfaces statistical signals, not investment recommendations. Nothing on the platform constitutes financial, investment, trading, or professional advice. Always do your own research or consult a qualified financial advisor.

## TROUBLESHOOTING
Can't log in:
1. Email not verified — check spam for noreply@baizora.firebaseapp.com, or click "Resend verification email" on the login page
2. Wrong password — use "Forgot password" link on login page; reset email comes from noreply@baizora.firebaseapp.com
3. No subscription — if login works but you're redirected to billing, your account has no active subscription; choose a plan

Subscribed but can't access dashboard: verify email first, then sign out and back in. If still stuck, email support@baizora.com.

Dashboard blank/not loading: (1) hard refresh Ctrl+Shift+R / Cmd+Shift+R, (2) sign out and back in, (3) try Chrome incognito, (4) check internet connection. Contact support if it persists.

Data not updated today: check it's a weekday and after 6–7 PM ET; do a hard refresh to bypass browser cache.

Verification email not received: check spam, search "baizora" or "firebaseapp", use "Resend" on login page. After 10 min, email support@baizora.com.

Respond in English. Be concise — 2–4 sentences for simple questions, a short list for complex ones.`;

const CHAT_SYSTEM_CN = `你是贝佐拉（Baizora）的客服助手，贝佐拉是一个美股大盘股价格与成交量分析平台。只回答与贝佐拉相关的问题，回答要简洁准确。

## 关于贝佐拉
- 追踪标普500和纳斯达克100所有成分股（约500+支美股大盘股）
- 数据在每个工作日（周一至周五）美股收盘后更新
- 深色海军蓝主题网页仪表板，支持中英双语
- 网站：hongzheduan.github.io | 联系邮箱：support@baizora.com

## 免费预览
无需登录，直接查看按日价格涨幅排名前3的股票。包含实时走势图、多周期统计和基本面数据（市盈率、市值、EPS、行业）。贝佐拉主页即可访问，是完整产品的真实体验。

## 注册与入门
1. 点击首页"免费注册"
2. 用邮箱+密码创建账户（至少6位，包含至少一个大写字母和一个数字）
3. 系统发送验证邮件（来自 noreply@baizora.firebaseapp.com），必须点击链接后才能登录（未收到请检查垃圾邮件夹）
4. 登录后：有效订阅用户直接进入个人主页；新用户/未订阅用户跳转至订阅页面
5. 在订阅页面选择月付或年付，完成 Stripe 付款后立即开始7天免费试用

## 价格方案
- 月付：$9.99/月
- 年付：$99/年（约$8.25/月，节省约17%）
- 两种方案功能完全相同——全部500+支股票、所有时间周期、走势图、基本面数据
- 首次订阅享受7天免费试用（每个邮箱仅限一次，且每张信用卡仅限一次）
- 试用结束后按所选方案自动续费
- 随时可取消——取消在当前计费周期结束时生效，不再产生后续费用
- 不提供订阅费用退款，建议充分利用免费试用期评估平台

## 订阅管理
- 账户页面：查看订阅状态、试用到期日期、取消订阅按钮
- "管理账单"按钮打开 Stripe 客户门户：更新支付方式、查看账单、切换方案、取消订阅
- 试用期内取消：不产生任何费用，访问权限持续至试用期结束

## 免费试用限制
- 每个邮箱地址仅限一次试用——以相同邮箱重新订阅将直接开始付费
- 每张信用卡仅限一次试用——无论用于哪个账户，已使用的信用卡将直接开始付费

## 数据与更新时间
- 扫描器每个工作日（周一至周五）美股收盘后运行
- 数据供应商盘后数据约在美东时间下午6:00到达，个人主页一般在下午6–7点之间更新
- 数据供应商偶尔延迟，属正常现象——稍等后刷新即可
- 周末/节假日：显示最近一个周五的收盘数据（正常现象）
- 价格、成交量、走势图、所有信号：最新交易日收盘数据
- EPS、市盈率、行业：来自 SEC EDGAR XBRL 申报文件，约每周刷新（公司提交新的10-Q/10-K季报/年报时更新）
- 贝佐拉使用TTM摊薄GAAP每股收益，与其他平台的"调整后"或"非GAAP"数据不同（GAAP包含一次性费用、重组成本等）

## 初步分析（Beta分析）
- 在美股收盘（下午4:00 ET）至完整扫描完成（下午6:30–7:00）之间，仪表板自动运行客户端"初步分析"，使用Tiingo实时收盘数据
- 首页显示："分析(初步)更新至：[今日日期]，完整数据下午6:30–7:00更新"
- 初步分析更新内容：价格、日价格变化、成交量(M)、日成交量变化、价格/MA21、量/MA21、今日K线柱
- 初步分析不更新：多周期统计（2周至1年）、评分、走势图——这些需要完整历史数据
- 完整扫描完成后：首页显示"分析(最终)更新至：[日期]"，所有数据全部刷新
- 下午4:00前的交易日：显示"分析更新至：[上次日期]（今日完整数据下午6:30–7:00更新）"
- 周末/节假日：不显示beta标签，只显示最近扫描日期

## 走势图标记（年趋势线列）
- ▲ 三角形 = 过去一年成交量最高的交易日。绿色 = 当日价格上涨；红色 = 当日价格下跌
- ● 圆圈（带光晕）= 过去一年单日最大价格变动日。绿色 = 成交量放大；红色 = 成交量萎缩
- 这些标记让您无需翻查数据，即可即时发现异常活动

## 仪表板数据列
固定列：
- 代码：股票代码
- 年趋势线：1年价格走势图（含事件标记）
- 价格：当前股价（美元）
- 成交量(M)：日成交量（百万股）
- 日价格变化：今日价格涨跌幅
- 价格/MA21：价格偏离21日均线程度
- 日成交量变化：今日成交量变化
- 量/MA21：成交量偏离21日均量程度

时间周期列（可选：1天/2周/1月/3月/6月/9月/1年）：
- 1天视图：当日价格/成交量变化及与MA21的比值
- 其他周期显示该期间总价格变化，以及窗口内单日最大价格和成交量变动及日期：
  - 总涨幅：该时间段内总价格变化
  - 日最大价涨：期间单日最大涨幅
  - 最大价涨日：最大涨幅日期
  - 量@价日：最大涨幅当天的成交量变化
  - 日最大量涨：期间单日最大成交量涨幅
  - 最大量涨日：最大成交量涨幅日期
  - 价@量日：最大成交量当天的价格变化

## 自选股（★ 收藏股票）
- 未登录时：保存在浏览器本地存储——清除缓存/Cookie、切换浏览器/设备或无痕模式均会丢失
- 登录后：自选股自动同步至云端，任何已登录设备均可恢复

## 重要免责声明
贝佐拉是数据智能平台，提供统计信号，非投资建议。平台上任何内容均不构成金融、投资或专业建议。请自主研究或咨询合格金融顾问后再做投资决策。

## 常见问题排查
无法登录：
1. 邮箱未验证——检查垃圾邮件夹中来自 noreply@baizora.firebaseapp.com 的邮件，或在登录页面点击"重新发送验证邮件"
2. 密码错误——在登录页面使用"忘记密码"重置，重置邮件来自 noreply@baizora.firebaseapp.com
3. 无有效订阅——登录成功但跳转至账单页面说明没有活跃订阅，选择方案即可

已订阅但无法进入主页：先确认邮箱已验证，再退出重新登录。问题持续请发邮件至 support@baizora.com。

主页空白/无法加载：(1) 强制刷新 Ctrl+Shift+R（Mac: Cmd+Shift+R），(2) 退出重新登录，(3) 尝试 Chrome 无痕模式，(4) 检查网络连接。

数据未更新：确认是工作日且在美东时间下午6–7点之后；做强制刷新清除浏览器缓存。

未收到验证邮件：检查垃圾邮件夹，搜索"baizora"或"firebaseapp"，使用登录页面的"重新发送"。10分钟后仍未收到请联系 support@baizora.com。

如果用户用中文提问，请用中文回答。简洁回复——简单问题2–4句，复杂问题用简短列表。`;

app.post("/chat", express.json(), async (req, res) => {
  const { message, history, lang } = req.body || {};

  if (!message || typeof message !== "string" || !message.trim()) {
    return res.status(400).json({ error: "Missing message" });
  }
  if (message.length > 500) {
    return res.status(400).json({ error: "Message too long" });
  }

  const isCN = lang === "cn";
  const safeHistory = Array.isArray(history) ? history.slice(0, 20) : [];

  try {
    const client = new Anthropic({ apiKey: anthropicKey.value() });

    const messages = safeHistory
      .filter(m => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string")
      .map(m => ({ role: m.role, content: m.content.slice(0, 1000) }));

    messages.push({ role: "user", content: message.trim() });

    const response = await client.messages.create({
      model: "claude-haiku-4-5",
      max_tokens: 1024,
      system: isCN ? CHAT_SYSTEM_CN : CHAT_SYSTEM_EN,
      messages,
    });

    const textBlock = response.content.find(b => b.type === "text");
    res.json({ reply: textBlock ? textBlock.text : "Unable to respond right now." });

  } catch (e) {
    console.error("chat:", e.message);
    res.status(500).json({ error: "Chat service unavailable" });
  }
});

/* ---------------------------
   EXPORT
--------------------------- */
exports.api = onRequest(
  { secrets: ["ANTHROPIC_API_KEY"] },
  app
);