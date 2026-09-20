// POST { email, device } -> one 14-day trial per email, no card required.

const {
  getStore, putStore, signToken, TRIAL_DAYS, json, normalizeEmail, validEmail,
} = require("./_lib");

module.exports = async (req, res) => {
  if (req.method !== "POST") return json(res, 405, { error: "POST only" });
  const { device } = req.body || {};
  const email = normalizeEmail((req.body || {}).email);
  if (!validEmail(email)) {
    return json(res, 400, { error: "Enter a valid email address." });
  }
  if (!device || typeof device !== "string" || device.length > 64) {
    return json(res, 400, { error: "missing device id" });
  }

  try {
    const data = await getStore(true);
    data.trials = data.trials || [];
    const existingTrial = data.trials.find((t) => t.email === email);
    const activeLicense = (data.licenses || []).find(
      (l) => l.email === email && l.status === "active"
    );

    if (activeLicense) {
      // Already a customer: treat this as activation, not a new trial.
      const exp = Math.floor(new Date(activeLicense.valid_until).getTime() / 1000);
      return json(res, 200, {
        token: signToken({ email, device, exp }),
        email,
        exp,
      });
    }

    let exp;
    if (existingTrial) {
      if (existingTrial.revoked) {
        return json(res, 403, { error: "This trial has ended." });
      }
      exp = Math.floor(new Date(existingTrial.expires).getTime() / 1000);
      if (Date.now() / 1000 > exp) {
        return json(res, 403, {
          error: "Your 14-day trial has ended. Buy Pro at whisperdictate.vercel.app",
        });
      }
    } else {
      exp = Math.floor(Date.now() / 1000) + TRIAL_DAYS * 86400;
      data.trials.push({
        email,
        device,
        started: new Date().toISOString(),
        expires: new Date(exp * 1000).toISOString(),
      });
      await putStore(data, `trial started: ${email}`);
    }

    return json(res, 200, {
      token: signToken({ email, device, exp, trial: true }),
      email,
      exp,
      trial: true,
    });
  } catch (err) {
    return json(res, 500, { error: "Activation service unavailable, try again later." });
  }
};
