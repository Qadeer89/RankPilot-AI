# Commercial SaaS delivery report

Branch `claude/serene-goodall-32a2wo`. Companion docs: `COMMERCIAL_SYSTEM.md` (audit, decisions, provider fact sheet),
`ENVIRONMENTS_AND_DOMAIN_MIGRATION.md` (env vars, deployment, backup/rollback, migration runbook).

## Headline

**Not production-ready for real payments yet.** Everything except the live provider round-trip is implemented and tested;
no Lemon Squeezy credentials existed in the build environment, so checkout creation, webhook payload shapes and the
refund/failed-payment event names have **never been exercised against the real provider**. Billing enforcement defaults
to `off`, so the existing real projects are unaffected until you switch it on.

## Test results (this environment)

| Suite | Result |
|---|---|
| Backend (pytest, real PostgreSQL + Redis) | **1068 passed** |
| Frontend type-check + ESLint | clean |
| Browser UI tests (Playwright, scripted fake API) | **45 passed** |
| Real local stack (uvicorn + Next dev + seeded DB), screenshots in `docs/screenshots/` | captured |
| Authorization against the real API | customer → admin endpoint **403**, forged `X-User-Role` header **403**, anonymous **401** |

Not run anywhere: any test against api.lemonsqueezy.com, a load test, a mobile-device test.

## Feature classification

| Feature | Status |
|---|---|
| Pricing ($15/mo, $150/yr in integer cents), 7-day trial config, plan display | Implemented & tested |
| One subscription per project, DB-enforced (partial unique indexes), several projects = independent subscriptions | Implemented & tested |
| Multiple target countries covered by one subscription | Implemented & tested (no per-country charge exists) |
| Webhook signature check (HMAC-SHA256 of raw body), idempotency, out-of-order protection, retry of failed events | Implemented & tested **against hand-built payloads** (signature scheme confirmed in provider docs) |
| Subscription state from provider object, no activation from browser events | Implemented & tested |
| Checkout creation via Lemon Squeezy API | **Implemented but mocked**: request/response shape taken from docs, never sent to the real API |
| Customer portal / update-payment links | Implemented but mocked (URLs come from provider payloads) |
| Trial rules (one trial per project, no-trial variant afterwards, expiry, reminder) | Implemented & tested; trial *collection of payment method at checkout* is a provider behaviour, unverified |
| Failed payment → past due → grace period → lock; recovery | Implemented & tested; the failed/recovered **event names are unverified** against the provider |
| Refund handling (first-payment full refund ends access; partial/renewal refunds only mark the payment) | Implemented & tested; `order_refunded` payload unverified |
| Reconciliation job (asks provider for truth on stale subscriptions) | Implemented, tested with a fake provider |
| Entitlement gate on crawls, AI, scheduled syncs, apply-change; read access never gated | Implemented & tested; modes off/log/enforce |
| One-time project replacement (atomic, locks, keeps subscription/trial/renewal/payments, admin exception) | Implemented & tested incl. concurrent attempts |
| Customer billing dashboard | Implemented & tested (UI tests + screenshot) |
| Super Admin: single account, verified email, server-side check on every route, route-introspection test | Implemented & tested |
| Super Admin dashboard: overview, users, projects, subscriptions, payments, revenue (MRR/ARR/cash/refunds/churn), trials, replacements, AI costs, webhooks, health, audit log, settings | Implemented & tested (figures verified against hand-computed seed data) |
| Admin actions: suspend/reactivate user and project, complimentary grant, replacement exception, webhook retry, runtime settings — reason + confirmation + audit | Implemented & tested |
| Extend trial | **Partially implemented**: only for complimentary (locally managed) access. A provider-billed trial must be extended in Lemon Squeezy; the API refuses rather than pretend. |
| Issue refunds from the dashboard | **Not implemented**: refunds are made in the Lemon Squeezy dashboard and recorded when the signed event arrives (the provider refund API call is unverified). |
| Correct "verified sync problems" | Partially: retry of failed events; reconciliation job. No manual field editing. |
| AI cost reporting | Implemented & tested; costs are **estimates** from tokens (labelled), chat/embedding calls excluded. |
| System health | Implemented & tested: API, DB, Redis queue depth, workers (live ping), failed jobs, webhook failures, failed payments, GA4 freshness, Google/CMS connection errors, configuration. |
| Alerts/thresholds | Partially: thresholds shown as warnings in AI costs and health; no push/email alerts. |
| Domain-independent configuration, environment guards, noindex outside production, robots/sitemap | Implemented & tested |
| Domain migration | **Not performed** by design; runbook written. |
| Staging environment itself | Not created (configuration supports it). |
| Email verification for the Super Admin | Implemented & tested; needs SMTP configured or the operator script |

## Money definitions (shown in the dashboard)

MRR = active + past-due provider-billed subscriptions, monthly price or annual ÷ 12; trials, cancelled, expired,
refunded and complimentary excluded. ARR = MRR × 12. Cash collected, refunds and net are period totals and are never
added to MRR/ARR. Currencies are grouped, never summed. Test-mode payments are excluded unless asked for.

## Known limitations

1. Provider integration unverified end-to-end (see headline). First real step: create a Lemon Squeezy **test** store,
   monthly/annual variants (with and without trial), set the env vars, run one test checkout and watch Admin → Integrations & Webhooks.
2. Billing-reason strings (`initial`, `renewal`) and invoice event names are assumptions from documentation.
3. Admin price/trial overrides change what RankPilot shows and validates; the amount charged is the variant's price in Lemon Squeezy.
4. Super Admin cannot access the dashboard until the email is verified (script or emailed link).
5. Existing real projects need a complimentary grant (or subscription) before `BILLING_ENFORCEMENT=enforce`.
6. UI tests use a scripted API; real-stack coverage is screenshots plus the authorization checks above.
7. Playwright browser tests were run on desktop width only.

## Screenshots (real local stack, seeded data)

`docs/screenshots/`: `customer-billing.png`, `customer-denied-admin.png`, `admin-overview.png`, `admin-users.png`,
`admin-projects.png`, `admin-subscriptions.png`, `admin-payments.png`, `admin-revenue.png`, `admin-trials.png`,
`admin-health.png`, `admin-audit.png`, `admin-settings.png`. The seeded subscriptions are demo rows, not real customers.
