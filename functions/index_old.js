// functions/index.js
const { defineSecret } = require("firebase-functions/params");
const functions = require("firebase-functions");
const express = require("express");
const Stripe = require("stripe");
const admin = require("firebase-admin");
const cors = require("cors");

admin.initializeApp();

const app = express();

/* ---------------------------
   Middleware
--------------------------- */
app.use(cors({ origin: true }));
app.use(express.json());

function getStripe() {
  // const key = functions.config().stripe.secret;
  

  if (!key) {
    throw new Error("Missing Stripe Secret Key");
  }

  return Stripe(key);
}

/* ---------------------------
   CONFIG
--------------------------- */
const DOMAIN = "https://baizora.com";

// Replace with YOUR real Stripe Price IDs
const MONTHLY_PRICE = "price_1TSJVFDRVR8GgjbGyMDrFqTr";
const YEARLY_PRICE  = "price_1TSIPMDRVR8GgjbGDyrT5E3C";

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
    console.error(e);
    res.status(500).json({
      ok: false,
      error: e.message
    });
  }
});

/* ---------------------------
   CREATE CHECKOUT SESSION
--------------------------- */
async function createCheckout(priceId, res) {
  try {
    const stripe = getStripe();

    const session = await stripe.checkout.sessions.create({
      mode: "subscription",

      line_items: [
        {
          price: priceId,
          quantity: 1
        }
      ],

      customer_creation: "always",

      billing_address_collection: "required",

      allow_promotion_codes: true,

      success_url: `${DOMAIN}/success.html?session_id={CHECKOUT_SESSION_ID}`,

      cancel_url: `${DOMAIN}/pricing.html`
    });

    res.json({ url: session.url });

  } catch (e) {
    console.error(e);
    res.status(500).json({ error: e.message });
  }
}

app.post("/create-monthly", async (req, res) => {
  await createCheckout(MONTHLY_PRICE, res);
});

app.post("/create-yearly", async (req, res) => {
  await createCheckout(YEARLY_PRICE, res);
});

/* ---------------------------
   CUSTOMER PORTAL
   (Cancel subscription / update card)
--------------------------- */
app.post("/customer-portal", async (req, res) => {
  try {
    const stripe = getStripe();
    const { customerId } = req.body;

    const session = await stripe.billingPortal.sessions.create({
      customer: customerId,
      return_url: `${DOMAIN}/dashboard.html`
    });

    res.json({ url: session.url });

  } catch (e) {
    console.error(e);
    res.status(500).json({ error: e.message });
  }
});

/* ---------------------------
   STRIPE WEBHOOK
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
        functions.config().stripe.webhook
      );
    } catch (err) {
      console.error("Webhook signature failed:", err.message);
      return res.status(400).send(`Webhook Error: ${err.message}`);
    }

    try {
      switch (event.type) {

        /* -------------------------
           PAYMENT SUCCESS
        ------------------------- */
        case "checkout.session.completed": {
          const session = event.data.object;

          const customerId = session.customer;
          const subscriptionId = session.subscription;

          const customer = await stripe.customers.retrieve(customerId);

          const email = customer.email || "";

          await admin.firestore()
            .collection("subscriptions")
            .doc(customerId)
            .set({
              email,
              customerId,
              subscriptionId,
              active: true,
              createdAt: admin.firestore.FieldValue.serverTimestamp()
            });

          console.log("Subscription activated:", email);
          break;
        }

        /* -------------------------
           SUBSCRIPTION UPDATED
        ------------------------- */
        case "customer.subscription.updated": {
          const sub = event.data.object;

          await admin.firestore()
            .collection("subscriptions")
            .doc(sub.customer)
            .set({
              active: sub.status === "active",
              status: sub.status,
              currentPeriodEnd: sub.current_period_end
            }, { merge: true });

          break;
        }

        /* -------------------------
           SUBSCRIPTION CANCELED
        ------------------------- */
        case "customer.subscription.deleted": {
          const sub = event.data.object;

          await admin.firestore()
            .collection("subscriptions")
            .doc(sub.customer)
            .set({
              active: false,
              canceled: true
            }, { merge: true });

          break;
        }

        default:
          console.log(`Unhandled event: ${event.type}`);
      }

      res.json({ received: true });

    } catch (e) {
      console.error(e);
      res.status(500).send("Webhook handler failed");
    }
  }
);

/* ---------------------------
   EXPORT
--------------------------- */
exports.api = functions.https.onRequest(app);
// exports.api = functions
//   .region("us-central1")
//   .runWith({ invoker: "public" }) // 👈 THIS is the key
//   .https.onRequest(app);