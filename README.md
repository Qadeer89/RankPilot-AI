# RankPilot AI

**Autonomous SEO Growth Platform.** Give us your website. We'll continuously find, implement
and validate SEO improvements.

The full product specification (v1.2, consolidated source of truth) lives in
[`docs/`](docs/README.md). Read it before changing scope or architecture; this README only
covers what's implemented so far and how to run it.

## Status

Phase 0 (environment readiness, documented here), Phase 1 (`MVP_IMPLEMENTATION_ROADMAP.md`,
"Platform foundation"), and Phase 2 ("Crawl and deterministic SEO baseline") are built:

- Authentication (register/login/me), organizations, role-based memberships, tenant isolation.
- Website registration with SSRF-safe URL validation (RP-0202) and a working domain
  ownership verification flow (`html_file` method, RP-0203).
- A bounded, SSRF-safe crawler (`apps/api/app/crawler/`): robots.txt + sitemap discovery
  (RP-0301), per-redirect-hop safety re-validation and size/time-limited fetching (RP-0302),
  HTML extraction into title/description/canonical/robots/headings/structured-data/internal-links
  (RP-0303), page snapshots (RP-0305), and a persisted, deduplicated crawl frontier (RP-0306).
- A deterministic SEO rule engine (`apps/api/app/seo_rules/`, RP-0401–RP-0407): HTTP status and
  redirect-chain checks, indexability/canonical checks, sitemap-inclusion checks, title/
  description/heading heuristics (labeled as heuristics, not confirmed errors, per
  `MASTER_SPEC.md` #8), structured-data parse-error detection, duplicate title/description
  detection, broken-internal-link detection, and orphan-page candidates. Findings are
  evidence-backed, upserted across crawls, and auto-resolve when a rule stops firing.
- `site_crawl` + `technical_audit` run as one Celery task per crawl (`app/tasks/crawl.py`),
  triggered via `POST .../crawls` and polled via `GET .../crawls/{id}`, `.../pages`,
  `.../findings`.
- Audit logging for sensitive actions.
- Health/readiness endpoints, structured JSON logging.
- Postgres schema + Alembic migrations, Celery worker/scheduler wiring against Redis.
- A minimal Next.js frontend (register, login, dashboard with add-website + verification UI;
  crawl/findings UI not yet built).

Not yet built: Search Console integration, AI agents, WordPress connector, billing. See
`docs/MVP_IMPLEMENTATION_ROADMAP.md` for the phase plan.

### Deliberate deviations from the doc pack

- `API_SPECIFICATION.md` lists bare `/websites` and `/crawls` routes. Both are implemented
  nested under `/organizations/{organization_id}/websites[/{website_id}]/...` instead, so
  tenant scoping is enforced by the route itself rather than trusted from a body field
  (`SECURITY_SPECIFICATION.md` #2: "Apply tenant scoping to every database query").
- Only the `html_file` verification method is implemented; `dns_txt` and `meta_tag` are declared
  in the schema for forward compatibility but not yet wired up.
- Playwright rendering fallback (RP-0304, for JS-rendered pages) is not implemented — the
  crawler is static-HTTP-only for now. Mobile/accessibility and page-performance signals
  (MASTER_SPEC.md #8) are out of scope until a Lighthouse-equivalent is integrated.
- Redirect-chain length is tracked per snapshot (`page_snapshots.redirect_count`), a column not
  explicitly listed in `DATABASE_SCHEMA.md`, needed for the `REDIRECT_CHAIN` rule.

## Repository layout

```
docs/           Product/architecture/security/QA spec pack (source of truth)
apps/api/       FastAPI backend + Celery worker/scheduler (modular monolith)
apps/web/       Next.js + TypeScript frontend
pm2/            PM2 process definitions for the shared VPS
```

## Local development

Prerequisites: Python 3.11+, Node 20+, PostgreSQL 16, Redis.

### Backend

```bash
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # edit RANKPILOT_DATABASE_URL / RANKPILOT_JWT_SECRET as needed
```

Create the local database once (adjust role/db names to match `.env`):

```bash
sudo -u postgres psql -c "CREATE ROLE rankpilot LOGIN PASSWORD 'rankpilot_dev';"
sudo -u postgres psql -c "CREATE DATABASE rankpilot OWNER rankpilot;"
```

Apply migrations and run the API:

```bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Run tests (needs the same local Postgres reachable; tests roll back everything they write):

```bash
pytest
```

Run the worker and scheduler (needs Redis):

```bash
celery -A app.celery_app worker --concurrency 1
celery -A app.celery_app beat
```

### Frontend

```bash
cd apps/web
npm install
cp .env.local.example .env.local   # points at the local API by default
npm run dev
```

Open http://localhost:3000, create an account, and add a website from the dashboard.

### Production processes (shared VPS)

See `pm2/ecosystem.config.js` and `docs/SYSTEM_ARCHITECTURE.md` #6-#7. Before deploying,
re-verify current CPU/RAM/disk headroom and existing Nginx/PM2 configuration on the host — the
figures in `docs/README.md` are point-in-time observations, not a capacity guarantee.

## Security notes for this scaffold

- The OpenAI API key, when added, must only ever be set as a server-side environment variable
  (`RANKPILOT_OPENAI_API_KEY`) — never committed, never sent to the frontend.
- The frontend currently stores the JWT in `localStorage` for simplicity. Before any real
  (non-founder-pilot) usage, move to an httpOnly session cookie per
  `docs/SECURITY_SPECIFICATION.md` #2.
- The SSRF-safe URL validator (`apps/api/app/core/url_safety.py`) is shared by website
  onboarding and the crawler's fetch layer (`apps/api/app/crawler/fetch.py`), which
  re-validates every redirect hop independently rather than trusting httpx's own
  `follow_redirects`.
