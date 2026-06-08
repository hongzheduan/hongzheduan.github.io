const functions = require("firebase-functions");
const express = require("express");
const Stripe = require("stripe");
const admin = require("firebase-admin");
const cors = require("cors");
const https = require("https");

const { defineSecret } = require("firebase-functions/params");

admin.initializeApp();

const app = express();

/* ---------------------------
   SECRETS
--------------------------- */
const stripeSecret = defineSecret("STRIPE_SECRET_KEY");
const stripeWebhookSecret = defineSecret("STRIPE_WEBHOOK_SECRET");
const tiingoKey = defineSecret("TIINGO_API_KEY");

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
    if (cached && (now - cached.ts) < 60_000) return res.json(cached.data);

    // Evict entries older than 2 minutes to keep the map small
    for (const [k, v] of _iexCacheMap) {
      if (now - v.ts > 120_000) _iexCacheMap.delete(k);
    }

    const data = await _tiingoGet(
      `https://api.tiingo.com/iex?tickers=${list.join(",")}&token=${tiingoKey.value()}`
    );
    const result = {};
    (Array.isArray(data) ? data : []).forEach(q => {
      const t = (q.ticker || "").toUpperCase();
      if (!t) return;
      const last = q.tngoLast ?? q.last;
      const prev = q.prevClose;
      result[t] = {
        last,
        chgPct: (prev && last) ? +((last - prev) / prev * 100).toFixed(2) : null,
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
   EXPORT
--------------------------- */
exports.api = functions.https.onRequest(app);