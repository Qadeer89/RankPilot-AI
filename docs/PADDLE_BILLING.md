# Paddle Billing — setup, operation and Live activation

RankPilot bills **per project** (one subscription = one website). Paddle Billing (not Classic) is a second payment provider next to
the existing Lemon Squeezy integration. Nothing changes until `RANKPILOT_BILLING_PROVIDER=paddle` is set.

## 1. Architecture (what was built)

| Piece | Where |
| --- | --- |
| Plan catalogue (`billing_plans`) | `app/models/billing.py`, `app/billing/catalog.py`, admin API `/admin/billing/plans` |
| Checkout (server decides plan, price, trial) | `app/billing/paddle_checkout.py` → Paddle `POST /transactions` → hosted checkout URL |
| Signed webhooks | `POST /api/v1/billing/webhooks/paddle` → `app/billing/paddle.py` (signature), `paddle_webhooks.py` (state machine) |
| Shared state machine (trial, grace, notifications) | `app/billing/webhooks.py::apply_subscription_object` (Paddle objects are translated to its shape) |
| Entitlements, usage limits, project allowance | `app/billing/features.py`, `entitlement.py`, `websites.py` (project cap) |
| Customer billing page | `apps/web/src/app/dashboard/billing` |
| Admin | Super Admin → *Plans & Pricing*, *Billing Customers*, *Integrations & Webhooks*, *Subscriptions*, *Payments* |
| Public pricing | `GET /api/v1/public/pricing` → only active + public + **approved** plans with a price |

Safety rules enforced in code (and covered by `tests/test_paddle_billing.py`):

* A browser redirect never activates anything. Only a signature-verified webhook creates or changes a subscription.
* A plan can be bought in **live** only if it is *approved* (price decided, Paddle price mapped, not a sandbox test plan). Sandbox
  test plans are sellable only while `RANKPILOT_PADDLE_ENV=sandbox`.
* No default price exists anywhere. A plan without a decided price is invisible and unbuyable.
* Expiry/cancellation never deletes projects, history, keywords or reports. Only new paid work is declined, and only when
  `RANKPILOT_BILLING_ENFORCEMENT=enforce`.
* GrowthPilot AI is a separate product; no entitlement is shared with it (separate database, separate Paddle products/prices).
* Secrets are server-side only. The client token is public by design (Paddle.js) and is the only Paddle value ever sent to a browser.

## 2. Environment variables (API, `apps/api/.env`)

```
RANKPILOT_BILLING_PROVIDER=paddle          # default lemonsqueezy
RANKPILOT_PADDLE_ENV=sandbox               # sandbox | live
RANKPILOT_PADDLE_API_KEY=                  # server-side key (pdl_sdbx_apikey_… / pdl_live_apikey_…)
RANKPILOT_PADDLE_CLIENT_TOKEN=             # public client-side token (test_… / live_…)
RANKPILOT_PADDLE_WEBHOOK_SECRET=           # the notification destination's endpoint secret key (pdl_ntfset_…)
RANKPILOT_API_PUBLIC_URL=https://<api-domain>
RANKPILOT_FRONTEND_BASE_URL=https://rankpilot.bugsnap-ai.com
RANKPILOT_BILLING_ENFORCEMENT=off          # off | log | enforce  (see §7)
```

Never commit these. Use the VPS `.env` (or the secret store of the environment). Sandbox and Live use different accounts, keys,
tokens and secrets — switch all four together with `PADDLE_ENV`.

## 3. Paddle dashboard configuration (done by you, in Sandbox first)

1. **Developer tools → Authentication**: create an API key (server) and a client-side token.
2. **Checkout → Checkout settings**: set a **Default payment link** on a domain approved in Paddle (e.g.
   `https://rankpilot.bugsnap-ai.com/pay`). Paddle refuses to return a checkout URL for transactions without it. The URL only has to
   exist on your domain; checkout itself is hosted by Paddle (`checkout.url`).
3. **Catalog**: one *product* (e.g. “RankPilot AI”). For each plan create the **price(s)** you decide:
   * *with trial* — a recurring price with a trial period;
   * *without trial* — the same recurring price without a trial (used when a customer already consumed their one trial).
   Prices are tax-exclusive/inclusive per your Paddle tax settings. **I have not chosen any price; you decide.**
4. **Developer tools → Notifications**: add a destination
   `https://<api-domain>/api/v1/billing/webhooks/paddle`, type *Webhook*, and subscribe to:
   `subscription.created`, `subscription.updated`, `subscription.activated`, `subscription.trialing`, `subscription.past_due`,
   `subscription.paused`, `subscription.resumed`, `subscription.canceled`, `transaction.completed`, `transaction.payment_failed`,
   `adjustment.created`, `adjustment.updated`. Copy the *secret key* into `RANKPILOT_PADDLE_WEBHOOK_SECRET`.
5. **Checkout/Customer portal**: enable the customer portal so “Manage billing” links work.

## 4. RankPilot configuration

1. Deploy, run migrations: `alembic upgrade head` (adds `billing_plans`, `billing_customers`, plan/provider columns and the `paddle` enum value).
2. Super Admin → **Plans & Pricing** → *New plan*: code, name, interval, price in cents, trial days, Paddle product/price ids, project
   limit, feature switches and usage limits. A new plan is created **inactive, unapproved, test-config**.
3. Sandbox: leave *Sandbox test configuration* ticked. The plan is buyable only while `PADDLE_ENV=sandbox`; the customer billing page labels it “(sandbox test)”.
4. Keep `RANKPILOT_BILLING_PROVIDER=paddle` and `RANKPILOT_BILLING_ENFORCEMENT=off` while testing.

## 5. Sandbox test plan

1. Create plan(s) with sandbox price ids; set `PADDLE_ENV=sandbox`.
2. In the app: Billing → choose the plan → *Start free trial* → Paddle checkout opens → pay with a Paddle sandbox test card.
3. Return to Billing: the page says “Confirming your payment…” and shows the subscription only after the webhook arrived.
4. Verify: Super Admin → Integrations & Webhooks shows `subscription.created` / `transaction.completed` as *processed*; Subscriptions and Payments show the rows.
5. Test: cancel (stays active until period end), change plan, failed payment (Paddle sandbox failing test card → `past_due` + grace), refund adjustment, retry of a failed webhook from the admin screen.

## 6. Lifecycle mapping

| Paddle | RankPilot status | Access |
| --- | --- | --- |
| `trialing` | trialing | yes |
| `active` | active | yes |
| `past_due` | past_due | yes during `RANKPILOT_BILLING_GRACE_DAYS`, then no |
| `paused` | paused | no |
| `active` + scheduled cancel | cancelled (ends at period end) | yes until `ends_at` |
| `canceled` | expired | no new paid work; **all data kept** |

Out-of-order events are ignored using Paddle's `occurred_at`. Duplicate events are stored once (`paddle:<event_id>`). A subscription
event that arrives before its checkout is linked returns 503 so Paddle retries (up to 15 times, then it is parked as *failed* for an admin to replay).

## 7. Enforcement

`RANKPILOT_BILLING_ENFORCEMENT=enforce` turns on: subscription requirement, plan feature switches, project cap (HTTP 402
`project_limit_reached` on project creation, also via the API). **Before enabling it**, grant every existing project a complimentary
entitlement (see `docs/COMMERCIAL_SYSTEM.md`) or existing customers will lose paid features.
Project allowance rule while strategy is open: the highest `max_projects` (capped by `max_websites`) among the workspace’s live Paddle
plans; no plan limit = unlimited. Replacement policy is not assumed; the existing one-time replacement flow is unchanged.

## 8. Going Live — exact steps (needs your explicit approval)

1. Decide prices; create **Live** products/prices in Paddle; complete Paddle account verification and the approved-domain / default payment link.
2. Create a Live API key, client token and notification destination (new secret).
3. On the VPS: set `PADDLE_ENV=live` and the four Live values together; restart api/worker.
4. In Plans & Pricing set the Live price ids on each plan, untick *Sandbox test configuration*, tick *Active* and *Public*, then **Approve**.
   (Approval is refused unless price, price id, and — for trial plans — the no-trial price id are present.)
5. Smoke test with one real low-value purchase and refund it; confirm webhook rows and the subscription.
6. Only then consider `RANKPILOT_BILLING_ENFORCEMENT=enforce`, and publish a refund policy / legal pages (needs legal review).

## 9. Not verified here

This environment has no Paddle account or outbound access to Paddle. The signature scheme, webhook payload shapes and API calls were
implemented from Paddle’s documentation and are exercised by tests with faked HTTP and self-signed webhooks. **Real checkout, real
webhook delivery, invoice PDF lookup, plan-change proration and customer-portal URLs are unverified until you run §5 in Sandbox.**
