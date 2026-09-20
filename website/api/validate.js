// POST { token } -> re-checks a device token; returns a fresh token when the
// license is still good (so renewals extend the client without a new
// activation), 403 when revoked, 401 when expired/invalid.

const {
  getStore, signToken, verifyToken, licenseActive, json,
} = require("./_lib");

module.exports = async (req, res) => {
  if (req.method !== "POST") return json(res, 405, { error: "POST only" });
  const payload = verifyToken((req.body || {}).token);
  if (!payload) return json(res, 401, { error: "invalid or expired token" });

  try {
    const data = await getStore(true);
    if (payload.trial) {
      const trial = (data.trials || []).find((t) => t.email === payload.email);
      if (!trial) return json(res, 403, { error: "trial revoked" });
      return json(res, 200, {
        token: signToken(payload),
        email: payload.email,
        trial: true,
        exp: payload.exp,
      });
    }
    const lic = (data.licenses || []).find((l) => l.email === payload.email);
    if (!licenseActive(lic)) {
      return json(res, 403, { error: "license inactive or expired" });
    }
    const exp = Math.floor(new Date(lic.valid_until).getTime() / 1000);
    return json(res, 200, {
      token: signToken({ email: payload.email, device: payload.device, exp }),
      email: payload.email,
      exp,
    });
  } catch (err) {
    // Store unreachable: the signed token itself stays authoritative until
    // its own expiry (the client also keeps a local offline grace period).
    return json(res, 200, {
      token: (req.body || {}).token,
      email: payload.email,
      exp: payload.exp,
      degraded: true,
    });
  }
};
