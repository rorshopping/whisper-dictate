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
  json, normalizeEmail, validEmail,
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

// Latest completed Checkout session for this email that started a
// subscription; returns { subscription, customer } or null.
async function findPaidSubscription(email) {
  const sessions = await stripeGet(
    `checkout/sessions?customer_details[email]=${encodeURIComponent(email)}` +
      `&status=complete&limit=10`
  );
  if (!sessions || !Array.isArray(sessions.data)) return null;
  const withSub = sessions.data.filter((s) => s.subscription);
  if (!withSub.length) return null;
  return withSub[0];
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
  const { email, key, device } = req.body || {};
  const normEmail = normalizeEmail(email);
  if (!key && !validEmail(normEmail)) {
    return json(res, 400, { error: "Enter the email you purchased with." });
  }
  if (!device || typeof device !== "string" || device.length > 64) {
    return json(res, 400, { error: "missing device id" });
  }

  try {
    const data = await getStore(true);
    let lic = findActiveLicense(data, { email: normEmail, key });

    if (!lic && normEmail && !key) {
      // Not in the store: verify the purchase with Stripe and provision.
      const session = await findPaidSubscription(normEmail);
      if (session) {
        const validUntil = await subscriptionValidUntil(session.subscription);
        if (validUntil) {
          const existing = (data.licenses || []).find(
            (l) => l.email === normEmail
          );
          if (existing) {
            existing.status = "active";
            existing.valid_until = new Date(validUntil * 1000).toISOString();
            existing.stripe_ids = Object.assign(
              existing.stripe_ids || {},
              { subscription: session.subscription, customer: session.customer }
            );
            lic = existing;
          } else {
            lic = {
              email: normEmail,
              key: null,
              status: "active",
              valid_until: new Date(validUntil * 1000).toISOString(),
              devices: [],
              created: new Date().toISOString(),
              source: "stripe-query",
              stripe_ids: {
                subscription: session.subscription,
                customer: session.customer,
              },
            };
            data.licenses.push(lic);
          }
          await putStore(data, `stripe-query provision: ${normEmail}`);
        }
      }
    }

    if (!lic) {
      return json(res, 403, {
        error: "No active license for that email. Buy at whisperdictate.vercel.app or start the trial.",
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
      await putStore(data, `activate device: ${lic.email}`);
    }

    const exp = Math.floor(new Date(lic.valid_until).getTime() / 1000);
    return json(res, 200, {
      token: signToken({ email: lic.email, device, exp }),
      email: lic.email,
      exp,
    });
  } catch (err) {
    return json(res, 500, { error: "Activation service unavailable, try again later." });
  }
};
