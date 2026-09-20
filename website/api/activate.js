// POST { email?, key?, device } -> issues a device token for an active license.
// Customers activate with the email they purchased with (or, for manual
// sales, the issued key). Max 3 devices per license.

const {
  getStore, putStore, signToken, findActiveLicense, MAX_DEVICES,
  json, normalizeEmail, validEmail,
} = require("./_lib");

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
    const lic = findActiveLicense(data, { email: normEmail, key });
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
