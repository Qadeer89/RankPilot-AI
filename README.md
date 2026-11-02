# RankPilot AI

**Autonomous SEO Growth Platform.** Give us your website. We'll continuously find, implement
and validate SEO improvements.

The full product specification (v1.2, consolidated source of truth) lives in
[`docs/`](docs/README.md). Read it before changing scope or architecture; this README only
covers what's implemented so far and how to run it.

## Status

Phase 0 (environment readiness, documented here), Phase 1 (`MVP_IMPLEMENTATION_ROADMAP.md`,
"Platform foundation"), Phase 2 ("Crawl and deterministic SEO baseline"), most of Phase 3
("Search performance and AI opportunities"), most of Phase 4 ("Safe execution"), and most of
Phase 5 ("Daily operations and reporting") are built:

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
  `.../findings`. The same task also refreshes opportunities (below) as its last step.
- Deterministic opportunity scoring (`apps/api/app/opportunities/`, RP-0603,
  `SEO_AUTOMATION_ENGINE.md` #3): a fixed per-rule-code table of impact/effort/risk_tier turns
  open findings into scored, explainable opportunities (`GET .../opportunities`). AI never
  decides impact or priority — only this deterministic scoring does.
- Google OAuth + Search Console integration (`apps/api/app/integrations/`, RP-0501–RP-0504):
  authorization-code flow with encrypted-at-rest token storage and automatic refresh,
  property listing/selection, and a sync job that stores click/impression/CTR/position data
  as `KeywordObservation` rows with an explicit "delayed and aggregated" freshness note on
  every read (`GET .../search-performance`).
- A server-side OpenAI Content Optimization Agent (`apps/api/app/ai/`, RP-0601/0602/0604/0607):
  drafts a title/meta-description proposal for one opportunity at a time, with page content
  wrapped and labeled as untrusted input the model must not treat as instructions
  (`AI_AGENT_SPECIFICATION.md` #6), a strict JSON-schema response format, an explicit
  operation allowlist re-checked in code (not just trusted from the schema), and a per-site
  daily USD budget enforced before every call (`POST .../opportunities/{id}/proposals`).
  Every call — including failed ones — is logged to `agent_runs` with token counts and
  estimated cost.
- A WordPress connector (`apps/api/app/connectors/wordpress.py`, RP-0703/0704) authenticating
  with a dedicated Application Password (never the owner's main account password), supporting
  `set_title` (reliable, core WordPress) and a best-effort `set_meta_description` (requires a
  Yoast-SEO-compatible REST-writable meta field; raises a clear `UnsupportedOperation` rather
  than silently no-op'ing when a site doesn't support it).
- A risk-tiered execution protocol (`apps/api/app/execution/`, RP-0701/0702/0705–0708,
  `SEO_AUTOMATION_ENGINE.md` #5): turning a proposal into one or more idempotent `SEOTask` rows,
  gating tier-1 changes on an explicit per-website opt-in and everything else on human approval,
  tier-3 blocked outright, before/after `ChangeRecord`s with deterministic post-change
  validation, and automatic rollback restricted to the one case
  `SEO_AUTOMATION_ENGINE.md` #8 allows it — validation failing immediately after the write that
  caused it. Pause/resume reuses the existing website status field from Phase 1.
- Celery Beat schedule (`apps/api/app/tasks/scheduler.py`, RP-0801): a daily crawl for every
  verified, active website (RP-0802 — a full re-crawl within budget each time, not true
  changed-page detection; see deviations), daily usage metering (RP-0806), a weekly report per
  website (RP-0805), and daily retention cleanup (RP-0807). "A daily schedule means daily
  checks, not forced daily edits" (`SYSTEM_ARCHITECTURE.md` #9) — crawling runs daily;
  execution still only happens through the same risk-tier/approval gates as a manual run.
- Credential-gated email notifications (`apps/api/app/notifications/email.py`, RP-0804): every
  send attempt is recorded as `sent`/`failed`/`skipped_not_configured`, never silently dropped.
- Deterministic per-site usage metering (`apps/api/app/usage/metering.py`, RP-0806) and a
  weekly activity report (`apps/api/app/reporting/weekly_report.py`, RP-0805) summarizing
  crawls, findings, opportunities and executed changes — with an explicit disclaimer that
  Search-Console figures aren't attributed to any specific change.
- Audit logging for sensitive actions, now with a read endpoint
  (`GET .../audit-events`, admin-only).
- Health/readiness endpoints, structured JSON logging.
- Postgres schema + Alembic migrations, Celery worker/scheduler wiring against Redis.
- A Next.js frontend covering the full backend surface: register/login/dashboard with
  add-website + verification, and a per-website detail page
  (`apps/web/src/app/dashboard/websites/[id]/`) with tabs for triggering and reading crawls,
  browsing findings, getting an AI proposal and turning it into a task, approving/rejecting/
  executing/rolling back tasks, connecting Google Search Console and WordPress, toggling the
  tier-1 auto-execute policy, and reading weekly reports.

- Backup/restore and incident-response runbooks (`ops/RUNBOOKS.md`, RP-0906) — specified in
  full, but **not yet run against a real host**: this environment has no production VPS to
  back up or restore. The verification log at the bottom of that file is empty until someone
  runs it for real.

## Beyond MVP (P1)

The MVP (Phases 0-5 above) is functionally complete end to end. Work since then is P1 scope
per `MASTER_SPEC.md` #5:

- **GA4 integration** (`apps/api/app/integrations/google_analytics.py`, `ga4_sync.py`):
  mirrors the Search Console integration — OAuth plumbing is shared
  (`google_oauth_common.py`, also refactored `token_store.py` to be provider-generic rather
  than hardcoded to Search Console), property listing via the Admin API's
  `accountSummaries`, a daily sessions/users/conversions sync via the Data API's `runReport`
  into `Ga4DailyMetric` rows, and a GA4 section in the weekly report. Same credential-gating
  pattern as Search Console (see below) — reuses the same Google OAuth client, a separate
  connection/scope/callback so a customer can grant one without the other.
- **The three remaining MVP agents** (`AI_AGENT_SPECIFICATION.md` #2, `apps/api/app/ai/`):
  - **Post-change QA Assistant** (`qa_assistant.py`): summarizes a `ChangeRecord`'s
    deterministic validation evidence in plain language. The `validation_status` it returns is
    always copied straight from the `ChangeRecord`, never decided by the model; if validation
    failed, a response using success-implying language ("successfully", "confirmed", ...) is
    rejected in code, not just discouraged in the prompt
    (`AI_AGENT_SPECIFICATION.md` #4: "it cannot declare success when checks fail").
  - **SEO Strategy Assistant** (`strategy_assistant.py`): a short weekly narrative + focus
    areas from the site's open opportunities. Rejected in code if it uses ranking-guarantee
    language ("guarantee", "will rank", ...) — `MASTER_SPEC.md`: "Do not promise or guarantee
    ranking increases."
  - **Internal Linking Analyst** (`apps/api/app/linking/candidates.py` +
    `apps/api/app/ai/internal_linking.py`): the deterministic half finds orphan pages (an open
    `ORPHAN_PAGE_CANDIDATE` finding) and a title-word-overlap shortlist of candidate source
    pages from the crawl graph; the AI half only picks from and explains that shortlist — it's
    rejected in code if it invents a source page outside it. Purely advisory: there's no
    WordPress connector operation for "add a link", so this never creates an executable
    `SEOTask`.
  - A shared `app/ai/runner.py` now holds the budget-enforcement/`AgentRun`-bookkeeping
    boilerplate all four agents (including the Phase 3 Content Optimization Agent, refactored
    to use it) share.
- **Agency multi-client overview** (`GET /organizations/{id}/overview`,
  `apps/api/app/api/v1/endpoints/organizations.py`): one row per website in the organization —
  verification/crawl status, open findings/opportunities/pending-task counts, last crawl — so
  an agency can triage which client sites need attention without opening each one.
- **Slack notifications** (`apps/api/app/notifications/slack.py`): a per-organization incoming
  webhook URL (`PATCH /organizations/{id}/settings`), stored encrypted the same way connector
  tokens are. `POST /organizations/{id}/notifications/slack/test` sends a test message and
  returns 409 if no webhook is configured yet. Same credential-gating pattern as
  email/Search Console — unconfigured is `skipped_not_configured`, not a crash.
- **Shopify and Webflow write connectors** (`apps/api/app/connectors/shopify.py`,
  `webflow.py`): same `set_title`/`set_meta_description` operation vocabulary as the WordPress
  connector, so the execution engine's risk-tier/approval/rollback machinery didn't need to
  change, only generalize. Shopify maps the two operations to the `global.title_tag` /
  `global.description_tag` metafields (the fields Shopify's own "Edit website SEO" panel
  writes), not the product/page's display title. Webflow maps them to the Data API v2 Pages
  resource's `title` / `seo.description`. Connect via
  `POST /organizations/{id}/websites/{id}/connections/{shopify|webflow}`.
- **GitHub connector for custom-code sites** (`apps/api/app/connectors/github_pr.py`,
  MASTER_SPEC.md #5: "GitHub/deployment integration"): a custom-code site has no live write
  API, so this connector never writes live — its one operation is opening a branch + commit +
  pull request with the proposed `<title>`/meta-description change, for a human to merge.
  Finds the file to edit via a short list of conventional static-site path guesses
  (`about.html`, `about/index.html`, `pages/about.html`, ...); a site that doesn't follow one of
  these conventions isn't supported yet. "Rollback" closes the still-open PR rather than
  reverting a live change, since nothing has shipped. "Validation" is correspondingly shallower
  than for a live connector — it confirms the PR is open and its diff contains the expected
  value, not that a deployed site serves it, which this platform can't observe without knowing
  the deploy pipeline. This is a deliberate, documented limitation, not an oversight.
- **Execution engine generalized to a connector dispatch** (`apps/api/app/execution/service.py`):
  the WordPress code path is untouched byte-for-byte; Shopify/Webflow/GitHub share one generic
  path keyed by a standardized `find_target`/`get_current_value`/`apply_change`/
  `validate_change`/`rollback` function set each new connector module implements. Which
  connector a website uses is resolved at execute time by which one has a `connected`
  `WebsiteConnection` row (`get_connected_content_connector`), not stored on the task.
- **Frontend UI for every P1 addition above**: GA4 connect/property-select/sync/metrics,
  Shopify/Webflow/GitHub connector connect/disconnect forms, and the three agent-triggering
  panels (QA summary on a task's change record, weekly Strategy Assistant narrative, Internal
  Linking Analyst orphan-page finder + suggestions) are in the website detail page's
  Integrations and new AI Agents tabs (`apps/web/src/app/dashboard/websites/[id]/`). The agency
  overview and Slack settings got their own page,
  `apps/web/src/app/dashboard/organization/page.tsx`, linked from the main dashboard.

Not yet built, and not buildable from inside this environment without more than code:

- **Load/resource testing on the shared VPS** (RP-0905): needs the actual host — its real
  CPU/RAM/disk, the other products already running on it, real network conditions. Numbers
  from this sandbox would not transfer and would be actively misleading if reported as if they
  did.
- **Founder pilot acceptance and beta go/no-go** (RP-0907): a product and business decision
  for the founder to make by using the product against real pilot sites, not something that
  gets built.
- Billing.

See `docs/MVP_IMPLEMENTATION_ROADMAP.md` for the phase plan.

### Credential-gated: Shopify, Webflow, GitHub

Same credential-gating pattern as every other connector: each is fully implemented and
unit-tested (external calls mocked), and the connect endpoint verifies the credential against
the live API before storing it (`ValueError` → `400`), so a bad shop domain, site ID, repo, or
token is rejected cleanly rather than stored. A real-service exercise from this sandbox hit a
genuine gap worth calling out: the connectors originally only turned a *bad HTTP status* into a
clean error — a network-level failure (DNS failure, connection refused, the sandbox's own
egress proxy) propagated as a raw `httpx` exception and 500'd instead. Fixed for all four
connectors (WordPress included) via a shared `safe_request()` helper in
`app/connectors/errors.py` that wraps every connector `httpx` call; verified with a live
Playwright smoke test (Shopify connect against an unreachable domain now returns `400`, not
`500`) and regression tests per connector.

### Credential-gated: email

Add **email notifications** to the credential-gated list above: it needs
`RANKPILOT_SMTP_HOST` / `RANKPILOT_SMTP_USERNAME` / `RANKPILOT_SMTP_PASSWORD`. Unset, every
send is recorded with status `skipped_not_configured` rather than raising.

### Credential-gated integrations

Both of the following are fully implemented and unit-tested (with the external call mocked),
but **not yet exercised against the real services**, since this environment has neither
credential:

- **Google Search Console** needs `RANKPILOT_GOOGLE_CLIENT_ID` / `RANKPILOT_GOOGLE_CLIENT_SECRET`
  (a Google Cloud OAuth client with the Search Console API enabled) and
  `RANKPILOT_GOOGLE_OAUTH_REDIRECT_URI` matching what's registered there. Unset, `/connect`
  returns a clear 503 rather than crashing.
- **GA4** needs the same `RANKPILOT_GOOGLE_CLIENT_ID` / `RANKPILOT_GOOGLE_CLIENT_SECRET` (the
  Admin API and Data API enabled on that OAuth client) plus
  `RANKPILOT_GOOGLE_GA4_OAUTH_REDIRECT_URI` (defaults to
  `.../integrations/google/analytics/callback`, a separate callback from Search Console's).
- **OpenAI** needs `RANKPILOT_OPENAI_API_KEY`. Unset, `/proposals` returns a clear 503. API
  billing is separate from a ChatGPT subscription (`AI_AGENT_SPECIFICATION.md` #3) — check the
  OpenAI platform account has credit before relying on this.

All three also need `RANKPILOT_TOKEN_ENCRYPTION_KEY` (generate with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
to encrypt OAuth tokens at rest. Rotating it invalidates every stored connection.

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
- `API_SPECIFICATION.md` lists bare `/integrations/google/search-console/connect` and
  `/opportunities/{id}/proposals` routes. Both are nested under the organization/website tenant
  path for the same reason as above, **except** the OAuth callback itself
  (`GET /integrations/google/search-console/callback`), which is intentionally left
  un-nested: it's a fixed redirect target Google calls directly, and recovers the
  organization from a signed `state` parameter instead of a path segment.
- Google's `webmasters.readonly` REST API is called directly over `httpx` rather than through
  `google-api-python-client`, to keep the dependency surface small and every request
  auditable in `app/integrations/google_search_console.py`.
- Four of `AI_AGENT_SPECIFICATION.md` #2's six MVP agents are implemented (Content
  Optimization, Post-change QA, SEO Strategy, Internal Linking Analyst). The "Execution
  Planner" agent isn't a separate AI call: `app/execution/service.py`'s
  `create_tasks_from_proposal` already deterministically converts a proposal's
  `proposed_actions` into typed `SEOTask` rows, which is that agent's whole job for the only
  operations this MVP supports (`set_title`, `set_meta_description`) — nothing about it
  benefits from an LLM call yet.
- The Internal Linking Analyst's AI call is advisory-only output (no executable `SEOTask`),
  since there's no WordPress connector operation for "add an internal link" yet.
- `site_crawl`, `technical_audit`, and `opportunity_refresh` are folded into one Celery task
  (`app/tasks/crawl.py`) rather than three separate job types, since opportunity scoring is
  cheap, deterministic, and always needs to follow a rule-engine pass.
- `API_SPECIFICATION.md`'s `/seo-tasks/{id}/...` and `/change-records/{id}/...` routes are
  nested under the organization/website tenant path, same as everywhere else.
- Approve/reject/execute/rollback all require the `admin` role, not `editor` — writing to a
  customer's live website is treated as more sensitive than reading or requesting a change.
- `requires_approval` on an `OpportunityProposal` is informational only; the actual gate is
  `app/execution/policy.py`, evaluated server-side from the website's `risk_tier` and
  `automation_policy`, never trusted from what the AI (or a client) claims.
- `change_records.page_id` isn't populated yet (`None`): the WordPress connector resolves a
  target by URL at execution time rather than by the crawler's `Page` row, so there's no
  `Page` lookup in the execution path yet to populate it from.
- `DATABASE_SCHEMA.md`'s `reports.storage_reference` assumes an external object store, which
  this MVP doesn't have; report content is stored inline as `reports.content_json` instead.
  Same for `oauth_connections`/`website_connections`, which already use a reference-style
  column name for what's actually an encrypted inline blob.
- "Changed-page recrawl" (RP-0802) isn't real incremental crawling yet — the daily scheduled
  crawl is a full re-crawl within the website's existing `crawl_budget`, the same as a manual
  "re-crawl" button would do. True changed-page detection (conditional requests, content-hash
  short-circuiting) is deferred.
- Weekly reports (RP-0805) are generated but not yet emailed automatically — there's no
  per-organization "who gets the weekly report" preference modeled yet, so
  `generate_weekly_reports` only writes the `Report` row; wiring it to
  `app/notifications/email.py` is straightforward once that preference exists.
- The website detail page's role-gated actions (approve/reject/execute/rollback, connecting
  WordPress, updating settings) all require the `admin` role server-side; the frontend doesn't
  hide those buttons for a lower-role viewer, it just surfaces the 403 the API returns. Role-
  aware UI (hiding vs. erroring) is a reasonable follow-up once there's more than one role in
  practice during the founder pilot.
- Every dynamic route under `apps/web/src/app/dashboard/` is split into a thin Server
  Component `page.tsx` (exporting `instant = false` and a `<Suspense>` boundary) wrapping the
  real `"use client"` page. Next.js 16's Cache Components model refuses to prerender a Client
  Component that reads `useParams()`/`useSearchParams()` outside Suspense, and route-segment
  config like `instant` can only be exported from a Server Component file — hence the split.
  New dynamic route pages should follow the same pattern (see
  `apps/web/src/app/dashboard/websites/[id]/page.tsx` for the wrapper and
  `website-detail-client.tsx` for the actual page).

## Repository layout

```
docs/           Product/architecture/security/QA spec pack (source of truth)
apps/api/       FastAPI backend + Celery worker/scheduler (modular monolith)
apps/web/       Next.js + TypeScript frontend
pm2/            PM2 process definitions for the shared VPS
ops/            Backup/restore and incident runbooks (RP-0906) — see ops/RUNBOOKS.md
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

Generate a token-encryption key (required even if you don't configure Google/OpenAI yet —
only the connect/sync/proposal endpoints need it at call time, but `oauth_connections` rows
can't round-trip without one):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# paste the output as RANKPILOT_TOKEN_ENCRYPTION_KEY in .env
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

- The OpenAI API key and Google OAuth client secret must only ever be set as server-side
  environment variables — never committed, never sent to the frontend. Same for
  `RANKPILOT_TOKEN_ENCRYPTION_KEY`.
- The frontend currently stores the JWT in `localStorage` for simplicity. Before any real
  (non-founder-pilot) usage, move to an httpOnly session cookie per
  `docs/SECURITY_SPECIFICATION.md` #2.
- The SSRF-safe URL validator (`apps/api/app/core/url_safety.py`) is shared by website
  onboarding and the crawler's fetch layer (`apps/api/app/crawler/fetch.py`), which
  re-validates every redirect hop independently rather than trusting httpx's own
  `follow_redirects`.
- Google OAuth access/refresh tokens are encrypted at rest (Fernet) in
  `oauth_connections.encrypted_token_reference` and never logged; disconnecting best-effort
  revokes the token with Google in addition to flipping local status.
- The AI content agent's user prompt explicitly labels crawled page content as untrusted and
  instructs the model not to treat it as instructions; its output is independently re-checked
  against an operation allowlist in code, not trusted from the JSON schema alone
  (`SECURITY_SPECIFICATION.md` #5).
- WordPress Application Passwords are encrypted at rest the same way OAuth tokens are, and
  `connect_wordpress` refuses to store a credential it hasn't first verified against the live
  site.
- Every `SEOTask` has an idempotency key derived from `(website, opportunity, operation,
  target_url)`, so a retried "create tasks" request can't create a duplicate pending change,
  and `execute_task` refuses to re-run a task that's already executing or completed.
