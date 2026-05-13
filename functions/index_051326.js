const functions = require("firebase-functions");
const express = require("express");
const Stripe = require("stripe");
const admin = require("firebase-admin");
const cors = require("cors");

const { defineSecret } = require("firebase-functions/params");

admin.initializeApp();

const app = express();

/* ---------------------------
   SECRETS
--------------------------- */
const stripeSecret = defineSecret("STRIPE_SECRET_KEY");
const stripeWebhookSecret = defineSecret("STRIPE_WEBHOOK_SECRET");

/* ---------------------------
   MIDDLEWARE
--------------------------- */
app.use(cors({ origin: true }));
// NOTE: express.json() is intentionally NOT added here globally.
// Each route that needs JSON parsing gets it explicitly below.
// The /webhook route must receive raw bytes for Stripe signature verification.

/* ---------------------------
   STRIPE INIT
--------------------------- */
function getStripe() {
  return new Stripe(stripeSecret.value());
}

/* ---------------------------
   HELPER: find or create Stripe customer by email
   This prevents duplicate customers for the same email.
--------------------------- */
async function findOrCreateCustomer(stripe, email) {
  // Search for existing customer by email
  const existing = await stripe.customers.list({ email, limit: 1 });

  if (existing.data.length > 0) {
    return existing.data[0].id;
  }

  // None found — create one
  const customer = await stripe.customers.create({ email });
  return customer.id;
}

/* ---------------------------
   HELPER: check if customer already has active/trialing sub
--------------------------- */
async function getActiveSubscription(stripe, customerId) {
  const subs = await stripe.subscriptions.list({
    customer: customerId,
    status: "all",
    limit: 10,
  });

  return subs.data.find(
    (s) => s.status === "active" || s.status === "trialing"
  ) || null;
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
   Key fix: reuse existing Stripe customer so no duplicates,
   and block double-subscription attempt.
--------------------------- */
const MONTHLY = "price_1TSJVFDRVR8GgjbGyMDrFqTr";
const YEARLY  = "price_1TSIPMDRVR8GgjbGDyrT5E3C";

async function createCheckout(priceId, email, res) {
  try {
    if (!email) {
      return res.status(400).json({ error: "Missing email" });
    }

    const stripe = getStripe();

    // Reuse existing customer or create fresh one
    const customerId = await findOrCreateCustomer(stripe, email);

    // Block if already subscribed
    const existingSub = await getActiveSubscription(stripe, customerId);
    if (existingSub) {
      return res.status(409).json({
        error: "already_subscribed",
        message: "This email already has an active subscription.",
        status: existingSub.status,
      });
    }

    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],

      // Use customer ID instead of customer_email — prevents new customer creation
      customer: customerId,

      subscription_data: {
        trial_period_days: 7,
      },

      success_url: "https://baizora.com/success.html",
      cancel_url: "https://baizora.com/pricing.html",
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
   Key fix: also store email in doc so get-user query works,
   and use subscriptionId as the doc key (not customerId)
   to avoid collisions when a customer had multiple subs.
--------------------------- */
app.post("/webhook", async (req, res) => {
    const stripe = getStripe();
    const sig = req.headers["stripe-signature"];

    let event;
    try {
      // Firebase Functions pre-parses the body — reconstruct raw buffer for Stripe
      let rawBody = req.rawBody; // Firebase provides this automatically
      if (!rawBody) {
        // Fallback: re-stringify the parsed body
        rawBody = JSON.stringify(req.body);
      }
      event = stripe.webhooks.constructEvent(
        rawBody,
        sig,
        stripeWebhookSecret.value()
      );
    } catch (err) {
      console.error("Webhook signature error:", err.message);
      return res.status(400).send(err.message);
    }

    if (event.type === "checkout.session.completed") {
      const session = event.data.object;
      try {
        // session.subscription can be null for one-time payments
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
            cancelAtPeriodEnd: subscription.cancel_at_period_end,
            currentPeriodEnd:  subscription.current_period_end,
            createdAt:         admin.firestore.FieldValue.serverTimestamp(),
          });
        console.log("Subscription written:", session.subscription, subscription.status);
      } catch (e) {
        console.error("checkout.session.completed error:", e.message);
        // Still return 200 so Stripe doesn't keep retrying a permanently broken event
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
          .set({                              // set+merge creates doc if missing
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
  }
);

/* ---------------------------
   GET USER SUBSCRIPTION
   Key fix: query by email (unchanged), but now the docs
   are keyed by subscriptionId so duplicates can't overwrite
   each other, and the status field is always fresh.
--------------------------- */
app.get("/get-user", async (req, res) => {
  try {
    const uid = req.query.uid;
    if (!uid) return res.status(400).json({ error: "Missing uid" });

    const userRecord = await admin.auth().getUser(uid);
    const email = userRecord.email;
    if (!email) return res.status(404).json({ error: "No email found" });

    // ── 1. Check new `subscriptions` collection (keyed by subscriptionId) ──
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

    // ── 2. Check old `users` collection (keyed by Firebase UID) ──
    const userDoc = await admin.firestore()
      .collection("users")
      .doc(uid)
      .get();

    if (userDoc.exists) {
      const userData = userDoc.data();
      const oldStatus = userData.subscriptionStatus || "inactive";

      // If old doc shows active/trialing, trust it and backfill to new schema
      if (oldStatus === "active" || oldStatus === "trialing") {
        // Try to get fresh data from Stripe if we have a subscriptionId
        if (userData.stripeSubscriptionId) {
          try {
            const stripe = getStripe();
            const sub = await stripe.subscriptions.retrieve(userData.stripeSubscriptionId);
            // Backfill into new subscriptions collection
            await admin.firestore()
              .collection("subscriptions")
              .doc(sub.id)
              .set({
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
            // Stripe lookup failed — fall through to return old status
            console.warn("Stripe sub lookup failed:", e.message);
          }
        }
        return res.json({ subscriptionStatus: oldStatus });
      }
    }

    // ── 3. Stripe fallback — search all customers for this email ──
    const stripe = getStripe();
    const customers = await stripe.customers.list({ email, limit: 10 });

    let activeSub = null;
    let foundCustomerId = null;

    for (const customer of customers.data) {
      const sub = await getActiveSubscription(stripe, customer.id);
      if (sub) {
        activeSub = sub;
        foundCustomerId = customer.id;
        break;
      }
    }

    if (activeSub) {
      // Backfill into new subscriptions collection
      await admin.firestore()
        .collection("subscriptions")
        .doc(activeSub.id)
        .set({
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

    const snapshot = await admin.firestore()
      .collection("subscriptions")
      .where("email", "==", email)
      .where("status", "in", ["trialing", "active"])
      .limit(1)
      .get();

    if (snapshot.empty) {
      return res.status(404).json({ error: "No active subscription" });
    }

    const data = snapshot.docs[0].data();
    if (!data.subscriptionId) {
      return res.status(400).json({ error: "Missing subscriptionId in DB" });
    }

    await stripe.subscriptions.update(data.subscriptionId, {
      cancel_at_period_end: true,
    });

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