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
    // Always fetch EN RSS (US-focused sources); translate titles for zh
    const url = `https://news.google.com/rss/search?q=${encodeURIComponent(_MARKET_NEWS_QUERY)}&hl=en-US&gl=US&ceid=US:en`;
    const resp = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36" },
      signal: AbortSignal.timeout(10000),
    });
    const xml = await resp.text();
    if (!xml.includes("<item>")) console.warn("market-news: 0 items from Google RSS. status:", resp.status, "preview:", xml.slice(0, 200));
    const parsed = _parseRssItems(xml).filter(it => !it.title.includes("?"));
    const items = parsed.slice(0, 10).map(it => ({
      title: it.title,
      source: it.source,
      link: it.link,
      date: new Date(it.pubDate).toISOString().slice(0, 10),
    }));
    if (lang === "zh") {
      for (const it of items) {
        const suffix = " - " + it.source;
        const clean = it.title.endsWith(suffix) ? it.title.slice(0, -suffix.length) : it.title;
        it.title_cn = await _translateToZh(clean);
        await new Promise(r => setTimeout(r, 80));
      }
    }
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
const CHAT_SYSTEM_EN = `You are a support assistant for Baizora (baizora.com), a US large-cap equity price & volume analytics platform. Answer questions about Baizora only. Support email: support@baizora.com.

## RESPONSE STYLE
- Your only job is to identify which page or FAQ item best answers the question, then reply with ONE sentence linking there. Do NOT explain anything yourself.
- If the question maps to a FAQ item, reply: See '[FAQ title]' in our [FAQ](https://baizora.com/assets/faq.html). — nothing else.
- Complete FAQ title list: "How does the Free Tier work?", "Do I need to sign up to use Baizora?", "How do I create an account?", "How do I access my dashboard and analysis results?", "Where do I go after logging in?", "How does the 7-day free trial work?", "How is the data updated?", "How current is the P/E and EPS data?", "What do the sparkline markers mean?", "What do the timeframe windows show?", "What stocks does Baizora cover?", "How accurate is the S&P 500 and Nasdaq-100 constituent list?", "Is Baizora a financial advisor or recommendation service?", "Where is my watchlist? My saved stocks are gone.", "How do I subscribe to a plan?", "How do I manage or cancel my subscription?", "What's the difference between monthly and yearly plans?", "What happens after the free trial ends?", "Can I use the same email address or credit card to get another free trial?", "What is your refund policy?", "I subscribed but can't access the dashboard — what should I do?", "I can't log in — I keep getting an error or being redirected.", "The data looks outdated — it hasn't updated today.", "I never received my verification email.", "The dashboard is blank or not loading."
- "What is Baizora?" or general platform questions → one sentence + [About Baizora](https://baizora.com/assets/about.html).
- Pricing/plans → [Pricing](https://baizora.com/pricing.html). Sign up → [Sign up](https://baizora.com/signup.html). Account/billing → [My Account](https://baizora.com/account.html).
- If no FAQ item fits → [FAQ](https://baizora.com/assets/faq.html). Suggest support@baizora.com only for account-specific issues (login failure, unexpected billing charge, subscription not activating).
- Do NOT use **bold** or other markdown — only [text](url) links are rendered.`;

const CHAT_SYSTEM_CN = `你是贝佐拉（Baizora）的客服助手，贝佐拉是一个美股大盘股价格与成交量分析平台。只回答与贝佐拉相关的问题。客服邮箱：support@baizora.com。

## 回答风格
- 你的唯一职责是判断哪个页面或常见问题条目最能回答该问题，然后用一句话附上链接。不要自行解释。
- 若问题对应某个常见问题条目，回复格式：请参阅[常见问题](https://baizora.com/assets/faq_cn.html)中的'[条目标题]'。——不加任何其他内容。
- 完整常见问题条目列表："免费版是如何运作的？"、"使用 Baizora 需要注册账户吗？"、"如何创建账户？"、"如何进入个人主页及查看分析结果？"、"登录后会跳转到哪里？"、"7天免费试用是如何运作的？"、"数据是如何更新的？"、"市盈率和每股收益数据有多新？"、"走势图上的标记代表什么？"、"时间周期窗口显示哪些信息？"、"Baizora 覆盖哪些股票？"、"标普500和纳斯达克100成分股名单的准确性如何？"、"Baizora 是投资顾问或推荐服务吗？"、"我的自选股去哪了？收藏的股票消失了。"、"如何订阅方案？"、"如何管理或取消我的订阅？"、"月付和年付方案有何区别？"、"免费试用结束后会发生什么？"、"我可以用相同的邮箱或信用卡再次获得免费试用吗？"、"退款政策是什么？"、"我已订阅但无法访问个人主页，该怎么办？"、"我无法登录——一直报错或被跳转。"、"数据看起来过期了，今天还没有更新。"、"我没有收到验证邮件。"、"个人主页空白或无法加载。"
- "贝佐拉是什么？"等平台总体问题 → 一句话 + [关于贝佐拉](https://baizora.com/assets/about_cn.html)。
- 价格方案 → [价格方案](https://baizora.com/pricing_cn.html)。注册 → [免费注册](https://baizora.com/signup_cn.html)。账户/账单 → [我的账户](https://baizora.com/account_cn.html)。
- 无对应条目 → [常见问题](https://baizora.com/assets/faq_cn.html)。仅账户专属问题（登录失败、账单异常、订阅未激活）才建议联系 support@baizora.com。
- 不要使用 **加粗** 等其他 markdown 格式——仅 [文字](url) 链接会被渲染。如果用户用中文提问，请用中文回答。`;

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
      max_tokens: 300,
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