# Stripe payment setup (live)

The website's "Buy Pro" button uses a Stripe **live-mode** payment link for a
yearly subscription. This file records exactly what exists so it can be
managed without archaeology.

## What exists (created 2026-09-20 via Stripe CLI)

| Object | ID | Notes |
|---|---|---|
| Account | `acct_1U30Ms4x3RJZCHSg` | Becker-Codehub (live + test keys via `stripe login`) |
| Product | `prod_VIPGVsatQvQof4` | "Whisper Dictate Pro (1 year)", tax code `txcd_10000000` (electronic services, required by Managed Payments) |
| Price | `price_1UHoSg4x3RJZCHSgnDjIsycR` | EUR 20.00, recurring every 1 year |
| Payment link | `plink_1UHoWv4x3RJZCHSg6Zse0QnP` | https://buy.stripe.com/dRmbIU4Ne4e11jG7u69AA02 |

The payment link redirects to `https://whisperdictate.vercel.app/thanks`
after checkout. The link URL is hardcoded in `website/index.html` (nav, hero,
pricing) — update it there if the price changes.

## Managing it

```bash
# Inspect / update the price (live mode)
stripe prices list --live --product prod_VIPGVsatQvQof4
stripe prices update <price_id> --live --nickname "..."   # amounts are immutable; create a new price instead

# Deactivate a payment link (kills checkout immediately)
stripe payment_links update plink_1UHoWv4x3RJZCHSg6Zse0QnP --live --active false

# See who paid
stripe checkout_sessions list --live --limit 10
# or in the Dashboard → Payments
```

## Caveats / roadmap

- There is **no automated license-key delivery**: buyers get a Stripe receipt
  and the /thanks page with download instructions. The receipt email is the
  license confirmation. If key-gating is ever added, hook
  `checkout.session.completed` via a Stripe webhook.
- Refunds: Dashboard → Payments → refund (14-day guarantee is documented in
  website/terms.html).
- VAT: Managed Payments is enabled on the account; Stripe calculates EU VAT
  from the buyer's country at checkout.
- The CLI stores masked keys only; use the Stripe Dashboard or `stripe login`
  to re-authenticate.
