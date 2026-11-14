# RankPilot AI — Deployment Guide

Companion to `ops/RUNBOOKS.md` (operational procedures: incident response,
backup/restore, key rotation) and `SYSTEM_ARCHITECTURE.md` (why things are
built this way). This document is the **how to actually deploy a change** —
written for the shared VPS this product currently runs on
(`pm2/ecosystem.config.js`, SYSTEM_ARCHITECTURE.md #7), not a generic
cloud-deployment tutorial.

## 1. Processes

Four PM2 processes, defined in `pm2/ecosystem.config.js`:

| Process | What it runs |
|---|---|
| `rankpilot-api` | FastAPI app (`uvicorn app.main:app`) |
| `rankpilot-worker` | Celery worker (background crawls, AI calls, connector writes) |
| `rankpilot-scheduler` | Celery beat (daily crawl, search/performance sync, retention, reports) |
| `rankpilot-web` | Next.js frontend |

On the actual shared VPS, ports and process names may differ from the
repo's `ecosystem.config.js` template (the server already hosts other
products) — check `pm2 describe <name>` for the real `script args` before
assuming a port.

## 2. Deploying a backend change

```bash
cd /opt/RankPilot-AI && git pull origin claude/serene-goodall-32a2wo && cd apps/api && .venv/bin/pip install -r requirements.txt && .venv/bin/python -m alembic upgrade head && pm2 restart rankpilot-api rankpilot-worker rankpilot-scheduler
```

If a change touches Playwright-based crawling (`app/crawler/render.py`),
also run `.venv/bin/python -m playwright install chromium` once after the
pip install — `CHROMIUM_EXECUTABLE_PATH` falls back to Playwright's own
downloaded browser (`~/.cache/ms-playwright/`) when the cloud-sandbox path
(`/opt/pw-browsers/chromium`) doesn't exist on this host.

## 3. Deploying a frontend change

```bash
cd /opt/RankPilot-AI/apps/web && npm install && npm run build && pm2 restart rankpilot-web
```

## 4. Required environment variables

Set as real server-side environment variables (PM2 `env` block or a
process manager's secret store) — never commit real values to
`apps/api/.env`. `apps/api/.env.example` lists every variable with the
shape it expects; the ones a fresh deployment actually needs:

| Variable | Required? | Purpose |
|---|---|---|
| `RANKPILOT_DATABASE_URL` | yes | PostgreSQL connection string |
| `RANKPILOT_REDIS_URL` | yes | Celery broker |
| `RANKPILOT_JWT_SECRET` | yes (production fails closed without it — RP13-002) | Session tokens |
| `RANKPILOT_TOKEN_ENCRYPTION_KEY` | yes once any OAuth/connector credential is stored | Encrypts OAuth tokens, connector secrets, Slack webhook URLs at rest |
| `RANKPILOT_OPENAI_API_KEY` | optional | AI proposal drafting; unset means every AI call fails closed with `AINotConfigured`, no crash |
| `RANKPILOT_GOOGLE_CLIENT_ID` / `_SECRET` | optional | Search Console + GA4 OAuth |
| `RANKPILOT_PAGESPEED_API_KEY` | optional | Core Web Vitals (Phase 4); free tier, no billing required |
| `RANKPILOT_SMTP_HOST` / `_USERNAME` / `_PASSWORD` | optional | Email notifications; unset means every email is recorded `skipped_not_configured` |

Every optional integration follows the same rule: unset means the
corresponding feature stays unmeasured/unsent, never a crash and never a
fabricated value.

## 5. Database migrations

Alembic, one linear history (`apps/api/migrations/versions/`). Always
`alembic upgrade head` as part of a backend deploy, even if the change
being deployed looks migration-free — a teammate's migration may already
be ahead of what's running. Never hand-edit a migration already merged to
the deploy branch; add a new one.

## 6. Scheduled jobs (Celery beat, `app/celery_app.py`)

| Job | Cadence | Notes |
|---|---|---|
| `daily_crawl_all_active_websites` | hourly | Per-website `crawl_frequency_hours` decides which sites are actually due (Phase 8) |
| `daily_sync_search_signals_for_all_websites` | 01:30 UTC | Search Console + GA4 |
| `daily-sync-url-inspection` | 01:45 UTC | Google's indexing view (Phase 5) |
| `daily-sync-performance-metrics` | 02:30 UTC | Core Web Vitals |
| `retention-cleanup-daily` | 03:00 UTC | Prunes old snapshots/audit events/notifications |
| `daily-usage-metering` | 04:00 UTC | |
| `weekly-reports-monday` | 05:00 UTC Monday | |

## 7. Rollback

A bad deploy: `git checkout <previous-commit>` on the server, reinstall
deps if `requirements.txt`/`package.json` changed, restart the affected
PM2 process(es). A bad **migration** does not auto-rollback — write and
run the specific `alembic downgrade` for that one revision; never
`downgrade -1` blindly against a database other sessions may already be
writing to.

## 8. Verifying a deploy

```bash
curl -s http://127.0.0.1:<api-port>/api/v1/health
```

Then `pm2 describe rankpilot-api` — `unstable restarts: 0` and a stable
`uptime` (not a few seconds, which indicates a crash loop) confirm the
process actually started cleanly rather than just reporting `online`
mid-restart-loop.
