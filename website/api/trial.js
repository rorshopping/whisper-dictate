// POST { email, device, product? } -> one 14-day trial per email PER PRODUCT,
// no card required. Already-paying customers (of that product) get an
// activation token instead.

const {
  getStore, putStore, signToken, TRIAL_DAYS, json, normalizeEmail, validEmail,
  licenseActive, sameProduct, DEFAULT_PRODUCT,
} = require("./_lib");

module.exports = async (req, res) => {
  if (req.method !== "POST") return json(res, 405, { error: "POST only" });
  const { device, product } = req.body || {};
  const email = normalizeEmail((req.body || {}).email);
  if (!validEmail(email)) {
    return json(res, 400, { error: "Enter a valid email address." });
  }
  if (product && !/^[a-z0-9_-]{1,32}$/.test(product)) {
    return json(res, 400, { error: "invalid product" });
  }
  if (!device || typeof device !== "string" || device.length > 64) {
    return json(res, 400, { error: "missing device id" });
  }

  try {
    const data = await getStore(true);
    data.trials = data.trials || [];
    const existingTrial = data.trials.find(
      (t) => t.email === email && sameProduct(t, product)
    );
    const activeLicense = (data.licenses || []).find(
      (l) => l.email === email && licenseActive(l) && sameProduct(l, product)
    );

    if (activeLicense) {
      // Already a customer: treat this as activation, not a new trial.
      const exp = Math.floor(new Date(activeLicense.valid_until).getTime() / 1000);
      return json(res, 200, {
        token: signToken({
          email, device, exp, product: activeLicense.product || DEFAULT_PRODUCT,
        }),
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
        const buy =
          (product || DEFAULT_PRODUCT) === "shipside"
            ? "Buy at shipside-app.vercel.app"
            : "Buy Pro at whisperdictate.vercel.app";
        return json(res, 403, {
          error: `Your 14-day trial has ended. ${buy}`,
        });
      }
    } else {
      exp = Math.floor(Date.now() / 1000) + TRIAL_DAYS * 86400;
      data.trials.push({
        email,
        device,
        product: product || DEFAULT_PRODUCT,
        started: new Date().toISOString(),
        expires: new Date(exp * 1000).toISOString(),
      });
      await putStore(data, `trial started: ${email} (${product || DEFAULT_PRODUCT})`);
    }

    return json(res, 200, {
      token: signToken({ email, device, exp, trial: true, product: product || DEFAULT_PRODUCT }),
      email,
      exp,
      trial: true,
    });
  } catch (err) {
    return json(res, 500, { error: "Activation service unavailable, try again later." });
  }
};
