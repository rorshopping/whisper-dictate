// Shared plumbing for the Whisper Dictate license API.
// The license database lives in the PRIVATE repo rorshopping/whisperdictate-admin
// (licenses.json); the API reads/writes it through the GitHub Contents API.
// Access tokens are HMAC-SHA256 signed, so the client can read but not forge
// them; the server re-issues a fresh token on every successful validation.

const crypto = require("crypto");

const REPO = "rorshopping/whisperdictate-admin";
const BRANCH = "master";
const STORE_PATH = "licenses.json";
const MAX_DEVICES = 3;
const TRIAL_DAYS = 14;

const HEADERS = {
  Authorization: `Bearer ${process.env.GH_TOKEN}`,
  Accept: "application/vnd.github+json",
  "User-Agent": "whisperdictate-license-api",
};

let cache = { data: null, sha: null, at: 0 };

async function gh(path, opts = {}) {
  const res = await fetch(`https://api.github.com${path}`, {
    ...opts,
    headers: { ...HEADERS, ...(opts.headers || {}) },
  });
  return res;
}

async function getStore(force = false) {
  if (!force && cache.data && Date.now() - cache.at < 30000) return cache.data;
  const res = await gh(`/repos/${REPO}/contents/${STORE_PATH}?ref=${BRANCH}`);
  if (!res.ok) throw new Error(`store read failed: ${res.status}`);
  const json = await res.json();
  cache = {
    data: JSON.parse(Buffer.from(json.content, "base64").toString("utf8")),
    sha: json.sha,
    at: Date.now(),
  };
  return cache.data;
}

async function putStore(data, message) {
  // Re-fetch the blob sha so concurrent writes don't clobber each other.
  const head = await gh(`/repos/${REPO}/contents/${STORE_PATH}?ref=${BRANCH}`);
  if (!head.ok) throw new Error(`store head failed: ${head.status}`);
  const sha = (await head.json()).sha;
  const content = Buffer.from(
    JSON.stringify(data, null, 2) + "\n",
    "utf8"
  ).toString("base64");
  const res = await gh(`/repos/${REPO}/contents/${STORE_PATH}`, {
    method: "PUT",
    body: JSON.stringify({ message, content, sha, branch: BRANCH }),
  });
  if (!res.ok) throw new Error(`store write failed: ${res.status} ${await res.text()}`);
  cache = { data, sha: (await res.json()).content.sha, at: Date.now() };
}

function b64url(buf) {
  return Buffer.from(buf).toString("base64url");
}

function secret() {
  const s = process.env.LICENSE_HMAC_SECRET;
  if (!s) throw new Error("LICENSE_HMAC_SECRET not set");
  return s;
}

function signToken(payload) {
  const body = b64url(JSON.stringify(payload));
  const sig = crypto
    .createHmac("sha256", secret())
    .update(body)
    .digest("base64url");
  return `${body}.${sig}`;
}

function verifyToken(token) {
  if (typeof token !== "string" || token.split(".").length !== 2) return null;
  const [body, sig] = token.split(".");
  const expect = crypto
    .createHmac("sha256", secret())
    .update(body)
    .digest("base64url");
  const a = Buffer.from(sig || "");
  const b = Buffer.from(expect);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  let payload;
  try {
    payload = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
  } catch {
    return null;
  }
  if (!payload.exp || Date.now() / 1000 > payload.exp) return null;
  return payload;
}

function licenseActive(lic) {
  return (
    lic &&
    lic.status === "active" &&
    new Date(lic.valid_until).getTime() > Date.now()
  );
}

function findActiveLicense(data, { email, key }) {
  return (data.licenses || []).find(
    (lic) =>
      licenseActive(lic) &&
      ((email && lic.email === String(email).toLowerCase()) ||
        (key && lic.key === key))
  );
}

function iso(daysFromNow) {
  return new Date(Date.now() + daysFromNow * 86400e3).toISOString();
}

function json(res, status, obj) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(obj));
}

function normalizeEmail(email) {
  return String(email || "").trim().toLowerCase();
}

function validEmail(email) {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email);
}

module.exports = {
  REPO,
  BRANCH,
  MAX_DEVICES,
  TRIAL_DAYS,
  getStore,
  putStore,
  signToken,
  verifyToken,
  licenseActive,
  findActiveLicense,
  iso,
  json,
  normalizeEmail,
  validEmail,
};
