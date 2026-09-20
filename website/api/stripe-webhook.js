// Stripe webhook: registers/extends/revokes licenses in the admin store.
// STRIPE_WEBHOOK_SECRET may hold several secrets (test + live), comma-separated.

const crypto = require("crypto");
const {
  getStore, putStore, normalizeEmail, validEmail,
} = require("./_lib");

module.exports.config = { api: { bodyParser: false } };

function verifySignature(rawBody, header) {
  const secrets = (process.env.STRIPE_WEBHOOK_SECRET || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (!secrets.length || !header) return false;
  const parts = Object.fromEntries(
    header.split(",").map((kv) => kv.split("="))
  );
  if (!parts.t || !parts.v1) return false;
  if (Math.abs(Date.now() / 1000 - Number(parts.t)) > 600) return false;
  const signedPayload = `${parts.t}.${rawBody}`;
  return secrets.some((s) => {
    const expect = crypto
      .createHmac("sha256", s)
      .update(signedPayload)
      .digest("hex");
    const a = Buffer.from(parts.v1);
    const b = Buffer.from(expect);
    return a.length === b.length && crypto.timingSafeEqual(a, b);
  });
}

async function readRaw(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.statusCode = 405;
    return res.end("POST only");
  }
  const raw = await readRaw(req);
  if (!verifySignature(raw, req.headers["stripe-signature"])) {
    res.statusCode = 400;
    return res.end("bad signature");
  }

  let event;
  try {
    event = JSON.parse(raw);
  } catch {
    res.statusCode = 400;
    return res.end("bad payload");
  }

  try {
    const data = await getStore(true);
    const type = event.type || "";
    const obj = event.data ? event.data.object : {};

    if (type === "checkout.session.completed") {
      const email = normalizeEmail(
        (obj.customer_details && obj.customer_details.email) ||
          (obj.customer_email || "")
      );
      if (!validEmail(email)) {
        res.statusCode = 200;
        return res.end("no email on session; skipped");
      }
      data.licenses = data.licenses || [];
      let lic = data.licenses.find((l) => l.email === email);
      const now = new Date();
      if (!lic) {
        lic = {
          email,
          key: "wd_" + crypto.randomBytes(16).toString("hex"),
          status: "active",
          valid_until: new Date(now.getTime() + 366 * 86400e3).toISOString(),
          devices: [],
          created: now.toISOString(),
          source: "stripe",
          stripe_ids: {},
        };
        data.licenses.push(lic);
      } else {
        lic.status = "active";
        const base = Math.max(
          Date.now(),
          new Date(lic.valid_until).getTime()
        );
        lic.valid_until = new Date(base + 366 * 86400e3).toISOString();
      }
      if (obj.subscription) lic.stripe_ids.subscription = obj.subscription;
      if (obj.customer) lic.stripe_ids.customer = obj.customer;
      if (obj.id) lic.stripe_ids.checkout_session = obj.id;
      await putStore(data, `stripe ${type}: ${email}`);
    } else if (type === "invoice.paid" && obj.subscription) {
      const email = normalizeEmail(
        (obj.customer_email || "")
      );
      const lic = data.licenses.find(
        (l) =>
          (email && l.email === email) ||
          l.stripe_ids.subscription === obj.subscription
      );
      if (lic) {
        const base = Math.max(
          Date.now(),
          new Date(lic.valid_until).getTime()
        );
        lic.valid_until = new Date(base + 366 * 86400e3).toISOString();
        lic.status = "active";
        await putStore(data, `stripe renewal: ${lic.email}`);
      }
    } else if (type === "customer.subscription.deleted") {
      const lic = data.licenses.find(
        (l) => l.stripe_ids && l.stripe_ids.subscription === obj.id
      );
      if (lic) {
        lic.status = "revoked";
        await putStore(data, `stripe subscription ended: ${lic.email}`);
      }
    }

    res.statusCode = 200;
    res.end("ok");
  } catch (err) {
    res.statusCode = 500;
    res.end("store error");
  }
};
