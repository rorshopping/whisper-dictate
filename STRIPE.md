# Stripe + licensing setup (live)

The website's "Buy Pro" button uses a Stripe **live-mode** payment link for a
yearly subscription (€40/year, required for all use). This file records what
exists and how the pieces fit together.

## Stripe objects (created 2026-09-20 via Stripe CLI)

| Object | ID | Notes |
|---|---|---|
| Account | `acct_1U30Ms4x3RJZCHSg` | Becker-Codehub |
| Product | `prod_VIPGVsatQvQof4` | "Whisper Dictate Pro (1 year)", tax code `txcd_10000000` (Managed Payments requirement) |
| Price (current) | `price_1UHpFH4x3RJZCHSg8lV3JBTH` | **EUR 40.00, recurring yearly** |
| Payment link (current) | `plink_1UHpFO4x3RJZCHSgsZ5lVUKu` | https://buy.stripe.com/9B614g0wY5i52nKg0C9AA03 → redirects to /thanks |
| ~~Price €20~~ | `price_1UHoSg4x3RJZCHSgnDjIsycR` | archived (initial pricing) |
| ~~Payment link €20~~ | `plink_1UHoWv4x3RJZCHSg6Zse0QnP` | archived |
| Webhook (test) | `we_1UHpLj4x3RJZCHSguyWafdJy` | → /api/stripe-webhook, secret in Vercel env |

## How licensing works

1. Customer pays via the payment link with their email.
2. `checkout.session.completed` hits `website/api/stripe-webhook.js`
   (deployed on Vercel with the site), which adds/extends the email in the
   **private** repo `rorshopping/whisperdictate-admin` (`licenses.json`).
   Renewals (`invoice.paid`) extend; cancellation at period end
   (`customer.subscription.deleted`) revokes.
3. The app's startup gate (`license_gate.py`) asks for the purchase email,
   `POST /api/activate` checks the store and issues a device-bound token
   (max 3 devices). `/api/validate` re-issues fresh tokens; the client keeps
   a 14-day offline grace. `/api/trial` gives one 14-day trial per email.
4. Messaging customers: private repo → Actions → "Message customers"
   (needs `SMTP_USER`/`SMTP_PASS` secrets there; a Gmail app password works).

Vercel env vars on project `whisperdictate`: `GH_TOKEN` (repo contents
access), `LICENSE_HMAC_SECRET` (token signing), `STRIPE_WEBHOOK_SECRET`
(comma-separated test + live secrets).

## ONE manual step left (live webhook)

The CLI's live restricted key lacks `webhook_write`, so the **live** webhook
endpoint must be created in the Dashboard (2 minutes):

1. https://dashboard.stripe.com/acct_1U30Ms4x3RJZCHSg/webhooks → **Add endpoint**
2. URL: `https://whisperdictate.vercel.app/api/stripe-webhook`
3. Events: `checkout.session.completed`, `invoice.paid`,
   `customer.subscription.deleted`
4. Copy the signing secret (`whsec_...`) and append it to the Vercel env var:
   `vercel env rm STRIPE_WEBHOOK_SECRET production` then re-add
   `"<test whsec>,<live whsec>"`, redeploy.

Until then, a live buyer appears in Stripe (and gets Stripe's receipt) but
must be registered manually: private repo → Actions → "Manage licenses" →
action=issue, email=<buyer email>. Then the app activation works.

## Managing / inspecting

```bash
stripe prices list --live --product prod_VIPGVsatQvQof4
stripe checkout_sessions list --live --limit 10   # who paid
stripe payment_links update plink_1UHpFO4x3RJZCHSgsZ5lVUKu --live -d "active=false"  # kill checkout
```

Refunds: Dashboard → Payments → refund (14-day guarantee is in
website/terms.html).
