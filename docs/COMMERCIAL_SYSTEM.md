# Commercial system: per-project subscriptions, Lemon Squeezy, Super Admin

Status: implementation in progress. This document is the Phase 0 audit and plan; later sections are filled in as
phases land. Nothing here is "production-ready" until the delivery report says it was tested for real.

## Phase 0: audit of the existing system

| Area | Finding |
|---|---|
| Billing / subscriptions | **None exist.** No payment provider code. `Organization.plan` (`solo`..`agency_plus`) is a legacy enum that nothing reads. |
| Tenancy | `Organization` is the tenant; users join through `Membership` (owner/admin/editor/viewer). A **project is a `Website`**, owned by an organization. |
| Auth | JWT bearer token kept in browser `localStorage` (no cookies, so no cookie-domain coupling). **No email verification exists.** `User.status` (`active`/`disabled`) exists. |
| Admin | `User.is_platform_admin` (DB flag) guards only the knowledge-base admin endpoints. No Super Admin dashboard. |
| Reusable | `AuditEvent` (append-only, SET NULL on org delete), `UsageRecord`, `AgentRun` (AI cost ledger), SMTP notification sender, `RequireRole`, Alembic, Celery scheduler, Playwright UI tests, central `Settings` (`RANKPILOT_` env prefix). |
| Hardcoded URLs | Defaults only in `Settings` (`frontend_base_url`, Google redirect URIs, `smtp_from_email`). Business logic has no hardcoded production domain. |
| Metered work to gate | manual / scheduled / webhook crawls, AI calls (`run_ai_agent`), scheduled GSC/GA4 syncs, growth generation. |

## Decisions made here (not in the spec)

1. **The customer is the organization; the purchaser is recorded.** A subscription belongs to one `Website` and one
   `Organization`, and stores the purchasing `user_id`. Billing actions need org owner/admin.
2. **Existing projects must not be locked out.** Entitlement enforcement has three modes
   (`RANKPILOT_BILLING_ENFORCEMENT` = `off` | `log` | `enforce`), default `off`. The Super Admin can grant a
   *complimentary* entitlement (provider `complimentary`, price 0, excluded from revenue) to existing projects before
   enforcement is switched on. Switching to `enforce` is an explicit, separate decision.
3. **Subscription state is derived from the subscription object**, not from event names alone, so a renamed or missing
   event cannot silently leave a project entitled (or locked).
4. **Super Admin = configured email + verified email + active account**, all checked server-side on every admin
   endpoint. `is_platform_admin` is left alone for the knowledge admin.

## Lemon Squeezy facts

Confirmed from Lemon Squeezy's documentation:
- Webhook signature: lowercase hex HMAC-SHA256 of the **raw body**, keyed with the signing secret you choose, sent in
  `X-Signature` ([Signing Requests](https://docs.lemonsqueezy.com/help/webhooks/signing-requests)).
- Event names seen in documentation/guides: `subscription_created`, `subscription_updated`, `subscription_cancelled`,
  `subscription_expired`, `subscription_paused`, `subscription_unpaused`, `subscription_resumed`, `order_created`,
  `subscription_payment_success`.
- A trial on a subscription product captures the payment method at checkout and delays the first charge to the end of
  the trial; trials are enabled per product with "Subscription has free trial?"
  ([free trials guide](https://docs.lemonsqueezy.com/guides/tutorials/saas-free-trials)). So **a payment method is
  required to start the 7-day trial**; a no-card trial would need a non-trial product and our own trial logic, which is
  not what the spec asks for.

**Not confirmed from documentation in this session** (handled defensively, to be verified with a real test-mode store):
`subscription_payment_failed`, `subscription_payment_recovered`, `order_refunded`, `subscription_payment_refunded`, the
status values (`on_trial`, `active`, `paused`, `past_due`, `unpaid`, `cancelled`, `expired`), and the checkout API's
custom-data / test-mode fields. Event name is always read from `meta.event_name` in the signed body, never from a header.

## Plan

0 audit; 1 data model + pricing config; 2 checkout + webhooks; 3 lifecycle + entitlement; 4 one-time replacement;
5 customer billing UI; 6 Super Admin security; 7-8 admin dashboard + monitoring; 9 domain independence + runbook;
10 testing + delivery report. Each phase is committed separately with its tests.
