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
2. In the app, they enter that email in the activation dialog. The
   activation API (`website/api/activate.js`, deployed on Vercel) verifies
   the purchase **directly against Stripe** (checkout session + subscription
   status read with the restricted key in `STRIPE_SECRET_KEY`), provisions
   the email in the private store (`rorshopping/whisperdictate-admin`,
   `licenses.json`) and issues a device-bound token (max 3 devices).
3. `/api/validate` re-issues fresh tokens; the client keeps a 14-day offline
   grace. On a 403 (expiry), the client silently re-activates — which
   re-reads the subscription's `current_period_end`, so renewals extend and
   cancellations end access **without any webhook**.
4. `/api/trial` gives one 14-day trial per email.
5. The Stripe webhook (`website/api/stripe-webhook.js`) is optional
   fast-path hardening: the test-mode endpoint is configured and verified;
   the live endpoint can be added in the Dashboard anytime (restricted key
   lacks `webhook_write`). Append its `whsec_` to the Vercel env
   `STRIPE_WEBHOOK_SECRET` (comma-separated).

Vercel env vars on project `whisperdictate`: `GH_TOKEN` (repo contents
access), `LICENSE_HMAC_SECRET` (token signing), `STRIPE_SECRET_KEY`
(restricted live key: checkout/subscription reads for activation),
`STRIPE_WEBHOOK_SECRET` (test secret; live optional).

## Messaging customers (no manual steps needed)

- **Automatic, in-app**: edit `website/notice.json` (`message`, `url`,
  `updated`) and deploy — every active install shows it as a tray
  notification once (the app compares `updated` with what it last showed).
- **Real email**: private repo → Actions → "Message customers" needs
  `SMTP_USER`/`SMTP_PASS` secrets (a Gmail app password is fine), OR run
  `scripts/message_outlook.ps1` locally while desktop Outlook is open.
- Purchase receipts/renewal emails are sent by Stripe automatically.

## Managing / inspecting

```bash
stripe prices list --live --product prod_VIPGVsatQvQof4
stripe checkout_sessions list --live --limit 10   # who paid
stripe payment_links update plink_1UHpFO4x3RJZCHSgsZ5lVUKu --live -d "active=false"  # kill checkout
```

Refunds: Dashboard → Payments → refund (14-day guarantee is in
website/terms.html).
