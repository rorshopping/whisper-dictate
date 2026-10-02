// POST { email?, key?, device } -> issues a device token for an active license.
// Customers activate with the email they purchased with (or, for manual
// sales, the issued key). Max 3 devices per license.
//
// If the store has no active license for the email, the purchase is verified
// directly against Stripe (checkout session + subscription status) and the
// store is provisioned on the fly - so licensing works even when the
// webhook path is unavailable; the webhook stays as fast-path hardening.

const {
  getStore, putStore, signToken, findActiveLicense, MAX_DEVICES,
  json, normalizeEmail, validEmail, sameProduct, parsePriceMap,
  DEFAULT_PRODUCT,
} = require("./_lib");

async function stripeGet(path) {
  const key = process.env.STRIPE_SECRET_KEY;
  if (!key) return null;
  const res = await fetch(`https://api.stripe.com/v1/${path}`, {
    headers: { Authorization: `Bearer ${key}` },
  });
  if (!res.ok) return null;
  return res.json();
}

// Which product a checkout session bought: payment-link metadata first,
// then the STRIPE_PRICE_MAP price lookup. Unmapped -> whisperdictate.
function productOfSession(session) {
  if (session.metadata && session.metadata.product) {
    return String(session.metadata.product).slice(0, 32);
  }
  const map = parsePriceMap();
  for (const item of (session.line_items && session.line_items.data) || []) {
    const m = map[item.price && item.price.id];
    if (m && m.product) return m.product;
  }
  return DEFAULT_PRODUCT;
}

// Latest completed Checkout session for this email that PAID for the
// requested product: a subscription start, or a one-time purchase whose
// payment-link metadata says plan=lifetime (perpetual license). Returns
// { session, validUntilEpoch } or null.
const LIFETIME_DAYS = 36500; // ~100 years: one-time purchases never expire

async function findPaidPurchase(email, product) {
  const sessions = await stripeGet(
    `checkout/sessions?customer_details[email]=${encodeURIComponent(email)}` +
      `&status=complete&limit=10&expand[]=data.line_items`
  );
  if (!sessions || !Array.isArray(sessions.data)) return null;
  for (const s of sessions.data) {
    if (!sameProduct({ product: productOfSession(s) }, product)) continue;
    if (s.subscription) {
      const end = await subscriptionValidUntil(s.subscription);
      if (end) return { session: s, validUntil: end };
    } else if (
      (s.metadata && s.metadata.plan === "lifetime") ||
      ((s.line_items?.data || []).some((li) => {
        const m = parsePriceMap()[li.price && li.price.id];
        return m && m.plan === "lifetime";
      }))
    ) {
      return { session: s, validUntil: Math.floor(Date.now() / 1000) + LIFETIME_DAYS };
    }
  }
  return null;
}

async function subscriptionValidUntil(subscriptionId) {
  const sub = await stripeGet(`subscriptions/${subscriptionId}`);
  if (!sub) return null;
  if (!["active", "past_due", "trialing"].includes(sub.status)) return null;
  const end = sub.current_period_end || sub.items?.data?.[0]?.current_period_end;
  return end ? Number(end) : null;
}

module.exports = async (req, res) => {
  if (req.method !== "POST") return json(res, 405, { error: "POST only" });
  const { email, key, device, product } = req.body || {};
  const normEmail = normalizeEmail(email);
  if (!key && !validEmail(normEmail)) {
    return json(res, 400, { error: "Enter the email you purchased with." });
  }
  if (product && !/^[a-z0-9_-]{1,32}$/.test(product)) {
    return json(res, 400, { error: "invalid product" });
  }
  if (!device || typeof device !== "string" || device.length > 64) {
    return json(res, 400, { error: "missing device id" });
  }

  try {
    const data = await getStore(true);
    let lic = findActiveLicense(data, { email: normEmail, key, product });

    if (!lic && normEmail && !key) {
      // Not in the store: verify the purchase with Stripe and provision.
      const purchase = await findPaidPurchase(normEmail, product);
      if (purchase) {
        const validUntil = purchase.validUntil;
        if (validUntil) {
          const existing = (data.licenses || []).find(
            (l) => l.email === normEmail && sameProduct(l, product)
          );
          if (existing) {
            existing.status = "active";
            existing.valid_until = new Date(validUntil * 1000).toISOString();
            const ids = Object.assign(existing.stripe_ids || {}, {
              checkout_session: purchase.session.id,
              customer: purchase.session.customer,
            });
            // Only overwrite the subscription id when this purchase really
            // was a subscription - one-time sessions have none.
            if (purchase.session.subscription) ids.subscription = purchase.session.subscription;
            existing.stripe_ids = ids;
            lic = existing;
          } else {
            lic = {
              email: normEmail,
              key: null,
              product: product || DEFAULT_PRODUCT,
              status: "active",
              valid_until: new Date(validUntil * 1000).toISOString(),
              devices: [],
              created: new Date().toISOString(),
              source: "stripe-query",
              stripe_ids: {
                subscription: purchase.session.subscription || undefined,
                checkout_session: purchase.session.id,
                customer: purchase.session.customer,
              },
            };
            data.licenses.push(lic);
          }
          await putStore(data, `stripe-query provision: ${normEmail} (${product || DEFAULT_PRODUCT})`);
        }
      }
    }

    if (!lic) {
      const buy =
        (product || DEFAULT_PRODUCT) === "shipside"
          ? "Buy at shipside-app.vercel.app or start the trial."
          : "Buy at whisperdictate.vercel.app or start the trial.";
      return json(res, 403, {
        error: `No active license for that email. ${buy}`,
      });
    }

    const devices = new Set(lic.devices || []);
    if (!devices.has(device)) {
      if (devices.size >= MAX_DEVICES) {
        return json(res, 403, {
          error: `This license is already active on ${MAX_DEVICES} machines. Contact support to move it.`,
        });
      }
      devices.add(device);
      lic.devices = [...devices];
      await putStore(data, `activate device: ${lic.email} (${lic.product || DEFAULT_PRODUCT})`);
    }

    const exp = Math.floor(new Date(lic.valid_until).getTime() / 1000);
    return json(res, 200, {
      token: signToken({
        email: lic.email,
        device,
        exp,
        product: lic.product || DEFAULT_PRODUCT,
      }),
      email: lic.email,
      exp,
    });
  } catch (err) {
    return json(res, 500, { error: "Activation service unavailable, try again later." });
  }
};
