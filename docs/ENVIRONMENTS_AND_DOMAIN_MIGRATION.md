# Environments, configuration and domain-migration runbook

Status: **readiness only**. No domain migration has been performed. Nothing in the code is tied to one
domain; every externally visible address comes from the settings below.

## 1. Environments are isolated by configuration

| Concern | development | staging | production |
|---|---|---|---|
| `RANKPILOT_ENVIRONMENT` | `development` | `staging` | `production` |
| Database / Redis | own instance | own instance | own instance (never shared) |
| Lemon Squeezy | test store, `RANKPILOT_LEMONSQUEEZY_TEST_MODE=true` | test store, test mode | live store, `…TEST_MODE=false` |
| Search engines | `noindex`, robots `Disallow: /` | same | indexable (`NEXT_PUBLIC_APP_ENV=production`) |
| `RANKPILOT_JWT_SECRET` | any | unique | unique; the API refuses to start on the default |

Safety nets (advisory; shown on **Admin → System Health → configuration** and logged at start-up; they
never stop a running API): production with test-mode payments, live payments outside production, local or
non-https URLs in production, CORS not containing the frontend, OAuth redirect host different from the API host.

## 2. Environment variables

Backend (`RANKPILOT_` prefix, `.env` or process environment). **Secrets are never shown in the UI.**

| Variable | Purpose | Secret |
|---|---|---|
| `ENVIRONMENT` | development / staging / production | no |
| `DATABASE_URL`, `REDIS_URL` | data stores | yes |
| `JWT_SECRET` | token signing (must be non-default in production) | yes |
| `FRONTEND_BASE_URL` | links in emails, checkout return URL, bot info page | no |
| `API_PUBLIC_URL` | public API address; webhook URL shown to admins | no |
| `CORS_ALLOWED_ORIGINS` | browser origins allowed to call the API | no |
| `CRAWLER_INFO_URL` | bot description page in the User-Agent (default `<frontend>/bot`) | no |
| `GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_GA4_OAUTH_REDIRECT_URI` | must be registered in Google Cloud | no |
| `SMTP_*`, `SMTP_FROM_EMAIL` | outgoing mail | password: yes |
| `OPENAI_API_KEY` | AI | yes |
| `SUPER_ADMIN_EMAIL` | the single Super Admin account (must also be email-verified) | no |
| `BILLING_ENFORCEMENT` | `off` (default) / `log` / `enforce` | no |
| `PRICE_MONTHLY_CENTS` (1500), `PRICE_ANNUAL_CENTS` (15000), `TRIAL_DAYS` (7), `BILLING_GRACE_DAYS` (7), `BILLING_CURRENCY` | defaults; the Super Admin may override at runtime | no |
| `LEMONSQUEEZY_API_KEY`, `LEMONSQUEEZY_WEBHOOK_SECRET` | provider credentials | yes |
| `LEMONSQUEEZY_STORE_ID`, `…_VARIANT_MONTHLY`, `…_VARIANT_ANNUAL`, `…_VARIANT_MONTHLY_NO_TRIAL`, `…_VARIANT_ANNUAL_NO_TRIAL`, `…_TEST_MODE`, `…_API_BASE` | provider catalogue | no |

Frontend: `NEXT_PUBLIC_API_BASE_URL` (API including `/api/v1`), `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_APP_ENV`.

## 3. Deployment of this release (existing VPS layout)

```bash
cd /opt/RankPilot-AI && git pull
cd apps/api && .venv/bin/alembic upgrade head   # a7d2c9e4b1f0 -> 265b952432b5 -> 3bdbaa8db8b2 -> 7712497bc82a -> d5f1c224d0de
.venv/bin/python scripts/verify_user_email.py --email <super-admin-email>   # or use the emailed link
cd ../web && npm ci && npm run build
pm2 restart rankpilot-api rankpilot-worker rankpilot-scheduler rankpilot-web
```

`BILLING_ENFORCEMENT` stays `off` until every real project has a subscription or a complimentary grant
(Admin → Projects → *Grant free access*). Only then switch to `log`, review, then `enforce`.

Add the Lemon Squeezy webhook in the provider dashboard pointing at the URL shown under
Admin → Settings → Deployment, subscribed to subscription and subscription-invoice events plus order refunds.

## 4. Backup and rollback

* Before migrating: `pg_dump -Fc rankpilot > /var/backups/rankpilot-$(date +%F-%H%M).dump`, and note the previous git SHA.
* The new tables only add data (subscriptions, payments, billing events, checkout sessions, trial history,
  replacements, admin settings, email verification tokens) plus `users.email_verified_at`; no existing column is altered or dropped.
* Code rollback: `git checkout <previous-sha>`, restart pm2. Old code ignores the new tables.
* Schema rollback (only if required): `alembic downgrade <revision>` step by step. This **drops billing data created
  since**, so restore from the dump instead once real payments exist.
* While `BILLING_ENFORCEMENT=off` nothing is blocked, so the feature set can be rolled out dark.

## 5. Domain-migration runbook (NOT executed)

1. Lower DNS TTL a day ahead. Take a database dump.
2. Provision TLS for the new frontend and API hostnames.
3. Update env: `FRONTEND_BASE_URL`, `API_PUBLIC_URL`, `CORS_ALLOWED_ORIGINS`, both Google redirect URIs,
   `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_SITE_URL`.
4. Register the new redirect URIs in Google Cloud **before** switching (keep the old ones until afterwards).
5. In Lemon Squeezy change the webhook URL to the new API address (Admin → Settings → Deployment shows it); keep the
   signing secret. Checkout return URLs are generated from `FRONTEND_BASE_URL` at checkout time.
6. Restart api, worker, scheduler, web. Admin → System Health → *configuration* must be `ok`.
7. 301-redirect the old hostnames at the proxy for at least the webhook retry window.
8. Verify: login, Google connection status, a test-mode checkout, a signed test webhook, a crawl.
9. Rollback = point DNS/proxy and the env values back; the database stores no RankPilot domain
   (only each customer's own site URLs).

## 6. Portability notes

State lives in PostgreSQL and Redis only; the application writes no files that must survive a redeploy, so API and
workers can be moved or scaled by pointing them at the same two services. The only host-specific path is the optional
Playwright browser location used for JS rendering.
