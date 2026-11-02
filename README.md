# RankPilot AI

**Autonomous SEO Growth Platform.** Give us your website. We'll continuously find, implement
and validate SEO improvements.

The full product specification (v1.2, consolidated source of truth) lives in
[`docs/`](docs/README.md). Read it before changing scope or architecture; this README only
covers what's implemented so far and how to run it.

## Status

Phase 0 (environment readiness, documented here) and the first slice of Phase 1
(`MVP_IMPLEMENTATION_ROADMAP.md`, "Platform foundation") are scaffolded:

- Authentication (register/login/me), organizations, role-based memberships, tenant isolation.
- Website registration with SSRF-safe URL validation (RP-0202) and a working domain
  ownership verification flow (`html_file` method, RP-0203).
- Audit logging for sensitive actions.
- Health/readiness endpoints, structured JSON logging.
- Postgres schema + Alembic migrations, Celery worker/scheduler wiring against Redis.
- A minimal Next.js frontend (register, login, dashboard with add-website + verification UI).

Not yet built: crawler, SEO rule engine, Search Console integration, AI agents, WordPress
connector, billing. See `docs/MVP_IMPLEMENTATION_ROADMAP.md` for the phase plan.

### Deliberate deviations from the doc pack

- `API_SPECIFICATION.md` lists bare `/websites` routes. Websites are implemented nested under
  `/organizations/{organization_id}/websites` instead, so tenant scoping is enforced by the
  route itself rather than trusted from a body field
  (`SECURITY_SPECIFICATION.md` #2: "Apply tenant scoping to every database query").
- Only the `html_file` verification method is implemented; `dns_txt` and `meta_tag` are declared
  in the schema for forward compatibility but not yet wired up.

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
  onboarding today and is intended for reuse by the Phase 2 crawler.
