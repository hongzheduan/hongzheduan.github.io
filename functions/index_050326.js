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

app.post("/create-checkout", async (req, res) => {
  try {
    const stripe = getStripe();

    const { email, plan } = req.body;

    const priceId =
      plan === "yearly"
        ? "price_1TSIPMDRVR8GgjbGDyrT5E3C"
        : "price_1TSJVFDRVR8GgjbGyMDrFqTr";

    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      customer_email: email,
      success_url: "https://baizora.com/success.html",
      cancel_url: "https://baizora.com/pricing.html"
    });

    res.json({ url: session.url });

  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

/* ---------------------------
   CHECKOUT
--------------------------- */
const MONTHLY = "price_1TSJVFDRVR8GgjbGyMDrFqTr";
const YEARLY  = "price_1TSIPMDRVR8GgjbGDyrT5E3C";

async function createCheckout(priceId, res) {
  try {
    const stripe = getStripe();

    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: "https://baizora.com/success.html",
      cancel_url: "https://baizora.com/pricing.html"
    });

    res.json({ url: session.url });

  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}

app.post("/create-monthly", (req, res) => createCheckout(MONTHLY, res));
app.post("/create-yearly", (req, res) => createCheckout(YEARLY, res));

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

      await admin.firestore()
        .collection("subscriptions")
        .doc(session.customer)
        .set({
          email: customer.email || "",
          active: true,
          createdAt: admin.firestore.FieldValue.serverTimestamp()
        });
    }

    res.json({ received: true });
  }
);

/* ---------------------------
   EXPORT (STABLE)
--------------------------- */
exports.api = functions.https.onRequest(app);