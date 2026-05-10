const functions = require("firebase-functions");
const express = require("express");
const Stripe = require("stripe");
const admin = require("firebase-admin");
const cors = require("cors");

const { defineSecret } = require("firebase-functions/params");

admin.initializeApp();

const app = express();

/* ---------------------------
   SECRETS (STABLE WAY)
--------------------------- */
const stripeSecret = defineSecret("STRIPE_SECRET_KEY");
const stripeWebhookSecret = defineSecret("STRIPE_WEBHOOK_SECRET");

/* ---------------------------
   MIDDLEWARE
--------------------------- */
app.use(cors({ origin: true }));
app.use(express.json());

/* ---------------------------
   STRIPE INIT
--------------------------- */
function getStripe() {
  return new Stripe(stripeSecret.value());
}

/* ---------------------------
   HEALTH CHECK
--------------------------- */
app.get("/", async (req, res) => {
  try {
    const stripe = getStripe();
    await stripe.balance.retrieve();

    res.json({
      ok: true,
      message: "Stripe Connected"
    });
  } catch (e) {
    res.status(500).json({
      ok: false,
      error: e.message
    });
  }
});

// app.post("/create-checkout", async (req, res) => {
//   try {
//     const stripe = getStripe();

//     const { email, plan } = req.body;

//     const priceId =
//       plan === "yearly"
//         ? "price_1TSIPMDRVR8GgjbGDyrT5E3C"
//         : "price_1TSJVFDRVR8GgjbGyMDrFqTr";

//     const session = await stripe.checkout.sessions.create({
//       mode: "subscription",
//       line_items: [{ price: priceId, quantity: 1 }],
//       customer_email: email,
//       subscription_data: {
//         trial_period_days: 7
//       },
//       success_url: "https://baizora.com/success.html",
//       cancel_url: "https://baizora.com/pricing.html"
//     });

//     res.json({ url: session.url });

//   } catch (e) {
//     res.status(500).json({ error: e.message });
//   }
// });

/* ---------------------------
   CHECKOUT
--------------------------- */
const MONTHLY = "price_1TSJVFDRVR8GgjbGyMDrFqTr";
const YEARLY  = "price_1TSIPMDRVR8GgjbGDyrT5E3C";

async function createCheckout(priceId, email, res) {
  try {
    const stripe = getStripe();

    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],

      customer_email: email,

      // REMOVE THIS BLOCK IF NO TRIAL PERIOD
      subscription_data: {
        trial_period_days: 7
      },

      success_url: "https://baizora.com/success.html",
      cancel_url: "https://baizora.com/pricing.html"
    });

    res.json({ url: session.url });

  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}

app.post("/create-monthly", (req, res) => createCheckout(MONTHLY, req.body.email, res));
app.post("/create-yearly", (req, res) => createCheckout(YEARLY, req.body.email, res));

/* ---------------------------
   WEBHOOK
--------------------------- */
app.post(
  "/webhook",
  express.raw({ type: "application/json" }),
  async (req, res) => {
    const stripe = getStripe();
    const sig = req.headers["stripe-signature"];

    let event;

    try {
      event = stripe.webhooks.constructEvent(
        req.body,
        sig,
        stripeWebhookSecret.value()
      );
    } catch (err) {
      return res.status(400).send(err.message);
    }

    if (event.type === "checkout.session.completed") {
      const session = event.data.object;

      const customer = await stripe.customers.retrieve(session.customer);
      const subscription = await stripe.subscriptions.retrieve(session.subscription);

      await admin.firestore()
        .collection("subscriptions")
        .doc(session.customer)
        .set({
          email: customer.email || "",
          customerId: session.customer,
          subscriptionId: session.subscription,

          status: subscription.status,
          cancelAtPeriodEnd: subscription.cancel_at_period_end,
          currentPeriodEnd: subscription.current_period_end,
          createdAt: admin.firestore.FieldValue.serverTimestamp()
        });
    }


    if (event.type === "customer.subscription.updated") {
      const sub = event.data.object;

      await admin.firestore()
        .collection("subscriptions")
        .doc(sub.customer)
        .update({
          status: sub.status,
          cancelAtPeriodEnd: sub.cancel_at_period_end,
          currentPeriodEnd: sub.current_period_end   
        });
    }

    if (event.type === "customer.subscription.deleted") {
      const sub = event.data.object;

      await admin.firestore()
        .collection("subscriptions")
        .doc(sub.customer)
        .update({
          status: "canceled",
          cancelAtPeriodEnd: false,
          canceledAt: admin.firestore.FieldValue.serverTimestamp()
        });
    }

    res.json({ received: true });
  }
);

/* ---------------------------
   GET USER SUBSCRIPTION
--------------------------- */

app.get("/get-user", async (req, res) => {

  try {

    const uid = req.query.uid;

    if (!uid) {
      return res.status(400).json({
        error: "Missing uid"
      });
    }

    // Get Firebase user
    const userRecord = await admin.auth().getUser(uid);

    const email = userRecord.email;

    if (!email) {
      return res.status(404).json({
        error: "No email found"
      });
    }

    // Find subscription by email
    const snapshot = await admin.firestore()
      .collection("subscriptions")
      .where("email", "==", email)
      .where("status", "in", ["trialing", "active"])
      .limit(1)
      .get();

    if (snapshot.empty) {
      return res.json({
        subscriptionStatus: "inactive"
      });
    }

    const sub = snapshot.docs[0].data()

    return res.json({
      // subscriptionStatus: "active"
      subscriptionStatus: sub.status, // "trialing", "active", "canceled"
      cancelAtPeriodEnd: sub.cancelAtPeriodEnd,
      currentPeriodEnd: sub.currentPeriodEnd
    });

  } catch (e) {

    console.error(e);

    res.status(500).json({
      error: e.message
    });

  }

});


app.post("/create-portal", async (req, res) => {
  try {
    const stripe = getStripe();

    const { uid } = req.body;

    if (!uid) {
      return res.status(400).json({ error: "Missing uid" });
    }

    const userRecord = await admin.auth().getUser(uid);
    const email = userRecord.email;

    if (!email) {
      return res.status(404).json({ error: "No email found" });
    }

    // find Stripe customer by email (you may need to store customerId later)
    const customers = await stripe.customers.list({
      email: email,
      limit: 1
    });

    if (!customers.data.length) {
      return res.status(404).json({ error: "Stripe customer not found" });
    }

    const customerId = customers.data[0].id;

    const portalSession = await stripe.billingPortal.sessions.create({
      customer: customerId,
      return_url: "https://baizora.com/dashboard.html"
    });

    res.json({ url: portalSession.url });

  } catch (e) {
    console.error(e);
    res.status(500).json({ error: e.message });
  }
});

/* ---------------------------
   CANCELLATION
--------------------------- */
app.post("/cancel-subscription", async (req, res) => {
  try {
    const stripe = getStripe();
    const { uid } = req.body;

    if (!uid) {
      return res.status(400).json({ error: "Missing uid" });
    }

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

    const doc = snapshot.docs[0];
    const data = doc.data();

    if (!data.subscriptionId) {
      return res.status(400).json({ error: "Missing subscriptionId in DB" });
    }

    await stripe.subscriptions.update(data.subscriptionId, {
      cancel_at_period_end: true
    });

    res.json({ success: true });

  } catch (e) {
    console.error(e);
    res.status(500).json({ error: e.message });
  }
});

/* ---------------------------
   EXPORT (STABLE)
--------------------------- */
exports.api = functions.https.onRequest(app);