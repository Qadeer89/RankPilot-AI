# RankPilot AI — v1.3 Complete Implementation & Readiness Requirements

**Document version:** 1.3  
**Prepared:** 2026-11-02  
**Purpose:** One consolidated reference covering product requirements, implementation facts verified from repository inspection, outstanding gaps, security controls, QA gates, deployment requirements, and the work required before calling RankPilot AI MVP-ready.

> **Status:** This is an implementation-aligned requirements and readiness reference. It does not claim that every requirement is implemented, tested, deployed, or production-ready. A code file existing is not proof that its behavior is complete. Every item must be validated through code review, automated tests, deployment checks, and pilot evidence.

---

# 1. Executive Summary

RankPilot AI is an **Autonomous SEO Growth Platform**. A website owner registers a website, verifies ownership, connects permitted data sources, receives a technical/on-page SEO baseline, reviews prioritized opportunities, and can authorize bounded changes. The platform validates changes and records evidence.

**Product promise:** “Give us your website. We'll continuously find, implement and validate SEO improvements.”

The product must not promise guaranteed rankings, traffic, indexing, or a fixed time to SEO results. Search performance depends on search engines, competitors, site quality, content, authority, market demand, and factors outside RankPilot's control.

Daily monitoring and opportunity discovery do not mean unnecessary daily website edits.

## 1.1 Confirmed product decisions

- Product name: **RankPilot AI**.
- Positioning: **Autonomous SEO Growth Platform**.
- Initial validation properties: founder-owned custom websites.
- AI provider: user's own OpenAI API key, configured server-side.
- Search performance source: Google Search Console first.
- Google Analytics 4: optional.
- Paid SEO data providers: not mandatory for MVP.
- First write connector: WordPress.
- Custom-code websites: read-only audit first; controlled deployment integration can follow.
- Architecture: Next.js, FastAPI, PostgreSQL, Redis, Celery, Python crawler, OpenAI API.
- Existing Database Mart VPS is the initial pilot host, subject to resource/load validation.
- PM2 is used for application process management where suitable.
- Automation policy: maximum useful autonomy with explicit permission, risk gates, validation, audit trail, and rollback where supported.

## 1.2 MVP outcome

A founder should be able to:
1. Sign in and create an organization.
2. Register a website.
3. Complete domain ownership verification.
4. Run a bounded crawl.
5. View pages, crawl status, technical findings, and prioritized opportunities.
6. Connect Google Search Console where available.
7. Receive AI-assisted explanations and bounded content proposals.
8. Connect WordPress with explicitly granted write scopes.
9. Approve or enable only eligible actions.
10. Execute an allowed change.
11. Validate the resulting page and preserve before/after evidence.
12. Review usage, AI costs, notifications, and audit history.

---

# 2. Product Scope and Non-Goals

## 2.1 MVP P0

- Authentication and organization tenancy.
- User memberships and server-side role checks.
- Website registration and ownership verification.
- SSRF-safe URL validation and fetching.
- Robots.txt and sitemap discovery.
- Bounded crawler with crawl budgets and queue controls.
- Page inventory and crawl snapshots.
- Deterministic technical/on-page SEO rule engine.
- Findings lifecycle: open, update, resolve.
- Deterministic opportunity scoring.
- Google Search Console OAuth and ingestion.
- OpenAI structured analysis and proposal generation.
- AI spend metering and per-site budget enforcement.
- Approval and risk-policy engine.
- WordPress connector for a small allowlisted set of write operations.
- Before/after change records.
- Post-change validation.
- Rollback only where the connector can restore the prior state.
- Daily scheduling and notifications.
- Dashboard for sites, crawls, findings, opportunities, tasks, and history.
- Security controls, audit events, retention, backup, monitoring, and usage limits.

## 2.2 P1

- GA4 integration.
- Agency client reporting and multi-site views.
- GitHub/deployment connector for custom-code websites.
- Slack notifications.
- More content and internal-linking workflows.
- Additional CMS connectors after connector-specific QA.

## 2.3 P2

- Optional Semrush/Ahrefs/Moz or other provider adapters.
- Advanced SERP, backlink, and competitor intelligence.
- Additional data providers only where customer demand, licensing, and unit economics justify them.

## 2.4 Explicit non-goals

- Replacing the entire Semrush/Ahrefs ecosystem in MVP.
- Building a global backlink index.
- Guaranteed rankings or traffic.
- Scraping Google SERPs in ways that violate terms.
- Unauthorized website publishing.
- Unbounded AI rewriting.
- Mandatory paid SEO data APIs.
- Ad management.
- Website builder.
- Link outreach marketplace.

---

# 3. Implementation Facts Verified in Repository Inspection

The following are code-level observations from repository files inspected on 2026-11-02. They are not claims that a production deployment or all tests have passed.

## 3.1 Backend and API structure

- Backend uses FastAPI.
- API prefix is `/api/v1`.
- Organization-scoped routes use `organization_id`.
- Website-scoped routes use both `organization_id` and `website_id`.
- Authentication identity is derived from a signed JWT.
- Membership and role checks must be performed server-side.
- Roles in the inspected model: `owner`, `admin`, `editor`, `viewer`.
- JWT default algorithm: `HS256`.
- Default access-token lifetime: 1,440 minutes.
- Development fallback JWT secret is `change-me-in-production`; it must never be used in production.

**Required action:** Keep the code's nested organization-scoped paths as the authoritative route contract. Do not implement older flat endpoint examples from earlier drafts without checking the actual router and schemas.

## 3.2 Website ownership verification

Current implemented method: **HTML file verification**.

Flow:
1. Generate a random token using `secrets.token_urlsafe(24)`.
2. Store the SHA-256 hash of the token.
3. Ask the site owner to publish `rankpilot-verify.txt` at the website root.
4. Fetch the verification file.
5. Use a 10-second timeout.
6. Do not follow redirects.
7. Compare the trimmed response body with the submitted token.

The verification model contains `dns_txt`, `html_file`, and `meta_tag` enum values, but only `html_file` is implemented in the inspected verification service.

**Gap:** The inspected implementation did not establish an enforced verification-token expiry. Do not document token expiry as implemented until code and tests prove it.

**Required actions:**
- Add expiry and replay protection.
- Add verification-attempt rate limiting.
- Define re-verification and revocation behavior.
- Add tests for wrong token, expired token, redirects, wrong host, oversized response, and DNS/HTTP edge cases.
- Implement DNS TXT or meta-tag verification only if needed; otherwise remove them from the user-facing available-method list until implemented.

## 3.3 Crawler

Verified implementation observations:
- Crawler is currently static HTTP; Playwright rendering fallback is not implemented.
- Crawl coordinator is synchronous/single-threaded inside one worker task.
- Shared-VPS pilot worker concurrency is intended to be 1.
- Default website crawl budget is 100 requested URLs per crawl.
- Website settings validation accepts crawl budgets from 1 to 10,000.
- Celery crawl task declares `max_retries=2`.
- This retry value applies to that crawl task, not every task or integration.
- The crawler uses robots policy and sitemap discovery.
- It stores page inventory and per-crawl snapshots.
- A page discovered through sitemap can be in the inventory even when it was not successfully fetched.

**Required actions:**
- Enforce a maximum response-body size.
- Enforce maximum redirect hops.
- Enforce per-host request rate and timeout policy.
- Revalidate every redirect target against SSRF protections.
- Bound sitemap recursion, sitemap size, decompression, and URL count.
- Bound HTML parsing and extracted link counts.
- Add crawl cancellation and per-site pause controls.
- Add duplicate crawl suppression and idempotent task handling.
- Make partial crawl failures visible without misreporting a crawl as a clean success.
- Record robots-blocked, skipped, error, fetched, and budget-exhausted counts separately.
- Add JavaScript rendering only as a controlled fallback after resource and security testing.
- Keep concurrency at 1 on the shared VPS until load testing supports a higher value.

## 3.4 AI runner and cost controls

Verified config defaults:
- Model: `gpt-4o-mini`.
- Request timeout: 30 seconds.
- Maximum output tokens: 1,200.
- Daily AI budget: USD 1.00 per website.
- OpenAI API key is optional in config; AI functions should report a clear unavailable state if unset.
- Shared AI runner checks per-site daily budget before a call.
- Agent runs record model, status, token counts, estimated cost, start/completion timestamps, and result reference.
- AI response is requested using a JSON schema and parsed into typed output.

**Important limitation:** The inspected configuration and budget code establish a per-site daily ceiling checked before calls. They do not establish a global spend ceiling or a fully atomic budget reservation under concurrent calls.

**Required actions:**
- Add a global daily/monthly AI spend cap.
- Make budget reservation atomic to prevent concurrent calls overspending.
- Define behavior when provider usage/cost is missing.
- Keep actual provider billing separate from estimated internal cost.
- Add maximum input size and prompt-context limits.
- Add retry policy only for retryable provider failures.
- Add model fallback policy only if output schemas and quality are revalidated.
- Keep API key server-side; never expose it in frontend bundles, browser storage, Git, logs, or customer-visible error traces.
- Add a kill switch for all AI calls.
- Ensure the budget check and agent-run ledger commit correctly even on exceptions and worker crashes.

## 3.5 SEO findings and opportunity scoring

The SEO engine is deterministic. AI must not decide whether a technical rule passes.

Opportunity score in the inspected model:

```python
risk_penalty = 1.0 - (risk_tier * 0.15)
effort_penalty = 1.0 / (1.0 + effort_estimate)
score = round(
    impact_estimate
    * confidence
    * effort_penalty
    * max(risk_penalty, 0.1),
    4,
)
```

The score is a prioritization heuristic, not a prediction of ranking or traffic improvement.

**Important:** Search Console metrics were not part of the inspected scoring formula. Earlier conceptual references to Search Console as a scoring input must not be presented as an implemented feature.

## 3.6 Connectors

Repository inspection confirms connector types for:
- WordPress
- Shopify
- Webflow
- GitHub

Connector presence does not prove that all operations are supported or production-ready. Consult each connector's implementation and allowlist. Keep MVP write scope narrow and WordPress-first.

**Required actions:**
- Document exact supported operations per connector.
- Document exact OAuth/API scopes.
- Add connector capability tests and permission tests.
- Never infer write access from a website URL or domain verification alone.
- Encrypt connector credentials at rest.
- Add disconnect/revoke and credential rotation procedures.
- Use per-connector operation allowlists.
- Verify remote state before and after each write.
- Record before/after state and actor identity.
- Only advertise rollback when restoration is tested for that exact operation.

## 3.7 Other implementation observations

- GA4 integration is present according to the repository's implementation status, but remains optional.
- Slack notification support is present according to the repository's implementation status.
- Four AI-call types in the inspected enum: `content_optimization`, `post_change_qa`, `seo_strategy`, `internal_linking`.
- Execution Planner is deterministic service logic, not a separately invoked LLM agent.
- Internal-linking recommendations are advisory unless an explicitly supported write operation is implemented and tested.
- Billing is not complete according to the repository status reviewed.
- Shared-VPS load/resource testing and founder-pilot acceptance remain outstanding.
- Do not treat these observations as a replacement for a full source/test/migration review.

---

# 4. Current SEO Rule Catalog

This section reflects the inspected files under `apps/api/app/seo_rules/rules/` and the opportunity template table. Thresholds are current code heuristics, not universal Google ranking requirements.

| Rule code | Current trigger | Severity | Confidence |
|---|---|---|---:|
| `HTTP_ERROR_STATUS` | Status missing or >= 400 | Warning for missing/4xx; Critical for >=500 | 1.0 |
| `REDIRECT_CHAIN` | Redirect hops > 1 | Warning | 1.0 |
| `NOINDEX_DIRECTIVE` | Robots directives contain `noindex` | Info | 1.0 |
| `CANONICAL_MISSING` | Canonical URL absent | Info | 0.8 |
| `CANONICAL_MISMATCH` | Normalized canonical differs from fetched URL | Warning | 0.9 |
| `TITLE_MISSING` | Title missing/empty | Critical | 1.0 |
| `TITLE_TOO_LONG` | Title length > 60 characters | Info | 0.6 |
| `TITLE_TOO_SHORT` | Title length < 15 characters | Info | 0.5 |
| `META_DESCRIPTION_MISSING` | Description missing/empty | Warning | 1.0 |
| `META_DESCRIPTION_TOO_LONG` | Description length > 160 characters | Info | 0.6 |
| `HEADING_H1_MISSING` | H1 count = 0 | Warning | 1.0 |
| `HEADING_MULTIPLE_H1` | H1 count > 1 | Info | 0.7 |
| `STRUCTURED_DATA_PARSE_ERROR` | Stored JSON-LD block has parse error | Warning | 1.0 |
| `DUPLICATE_TITLE` | Exact non-empty title occurs on 2+ crawl snapshots | Warning | 1.0 |
| `DUPLICATE_META_DESCRIPTION` | Exact non-empty description occurs on 2+ crawl snapshots | Warning | 1.0 |
| `BROKEN_INTERNAL_LINK` | Internal link target is known and latest status >=400 | Warning | 1.0 |
| `ORPHAN_PAGE_CANDIDATE` | Sitemap URL is not a target of any observed internal link | Info | 0.6 |
| `SITEMAP_URL_ERROR` | Sitemap URL has a known page with latest status >=400 | Warning | 1.0 |

## 4.1 Rule limitations

- Duplicate checks are exact-string comparisons, not semantic duplicate detection.
- Broken-link checks do not classify unknown/un-crawled targets as broken.
- Orphan-page detection is a candidate heuristic; incomplete crawl coverage can affect it.
- Character length is Python string length, not SERP pixel width.
- Search engines may rewrite titles and snippets.
- Missing canonical, noindex, and canonical mismatch may be intentional.
- Structured-data rule checks parse errors; it does not certify schema correctness or rich-result eligibility.
- Static HTTP crawling may miss JavaScript-rendered content.

## 4.2 Opportunity promotion mapping

Only these rules currently become opportunities:

| Rule | Impact | Effort | Risk tier | Opportunity |
|---|---:|---:|---:|---|
| `TITLE_MISSING` | 0.8 | 0.2 | 1 | Add a missing page title |
| `META_DESCRIPTION_MISSING` | 0.5 | 0.2 | 1 | Add a missing meta description |
| `DUPLICATE_TITLE` | 0.7 | 0.3 | 1 | Resolve a duplicate page title |
| `DUPLICATE_META_DESCRIPTION` | 0.4 | 0.3 | 1 | Resolve a duplicate meta description |
| `CANONICAL_MISSING` | 0.3 | 0.3 | 1 | Add a canonical tag |
| `CANONICAL_MISMATCH` | 0.6 | 0.4 | 2 | Fix a mismatched canonical tag |
| `HTTP_ERROR_STATUS` | 0.9 | 0.5 | 1 | Fix a broken page |
| `BROKEN_INTERNAL_LINK` | 0.5 | 0.2 | 1 | Fix a broken internal link |
| `REDIRECT_CHAIN` | 0.3 | 0.3 | 1 | Shorten a redirect chain |
| `STRUCTURED_DATA_PARSE_ERROR` | 0.4 | 0.4 | 1 | Fix invalid structured data |
| `ORPHAN_PAGE_CANDIDATE` | 0.4 | 0.4 | 1 | Add internal links to an orphan page |
| `SITEMAP_URL_ERROR` | 0.5 | 0.3 | 1 | Fix a broken sitemap entry |

These findings remain findings only and are not currently promoted to opportunities:
- `TITLE_TOO_LONG`
- `TITLE_TOO_SHORT`
- `META_DESCRIPTION_TOO_LONG`
- `HEADING_H1_MISSING`
- `HEADING_MULTIPLE_H1`
- `NOINDEX_DIRECTIVE`

---

# 5. Database Model and Integrity Requirements

The following enum values were verified in inspected model files. Verify Alembic migrations and the deployed database before schema changes.

| Domain | Current enum values |
|---|---|
| User status | `active`, `disabled` |
| Organization status | `active`, `suspended`, `deleted` |
| Organization plan | `solo`, `business`, `pro`, `agency`, `agency_plus` |
| Membership role | `owner`, `admin`, `editor`, `viewer` |
| Website verification status | `unverified`, `pending`, `verified`, `failed` |
| Website platform | `unknown`, `wordpress`, `custom` |
| Website status | `active`, `paused`, `deleted` |
| Verification method | `dns_txt`, `html_file`, `meta_tag` |
| Crawl trigger | `manual`, `scheduled` |
| Crawl status | `pending`, `running`, `completed`, `failed` |
| Page indexability | `unknown`, `indexable`, `noindex`, `blocked_by_robots` |
| Finding severity | `info`, `warning`, `critical` |
| Finding status | `open`, `resolved` |
| Opportunity status | `open`, `dismissed`, `completed` |
| SEO task status | `pending`, `approved`, `rejected`, `executing`, `completed`, `failed` |
| Approval status | `not_required`, `pending`, `approved`, `rejected` |
| Approval decision | `pending`, `approved`, `rejected` |
| Change actor type | `user`, `system`, `ai` |
| Validation status | `pending`, `passed`, `failed` |
| Rollback status | `pending`, `completed`, `failed`, `unavailable` |
| Connector type | `wordpress`, `shopify`, `webflow`, `github` |
| Website connection status | `connected`, `disconnected`, `error` |
| OAuth provider | `google_search_console`, `google_analytics` |
| OAuth connection status | `connected`, `disconnected`, `error` |
| Agent type | `content_optimization`, `post_change_qa`, `seo_strategy`, `internal_linking` |
| Agent run status | `pending`, `succeeded`, `failed` |
| Notification channel | `email`, `slack` |
| Notification status | `pending`, `sent`, `failed`, `skipped_not_configured` |

## 5.1 Verified uniqueness constraints

Inspected models explicitly declare:
- `organizations.slug`
- `users.email`
- `memberships(organization_id, user_id)`
- `pages(website_id, normalized_url)`
- `seo_findings(website_id, page_id, rule_code)`
- `seo_tasks.idempotency_key`
- `website_connections(website_id, connector_type)`
- `oauth_connections(organization_id, provider)`

## 5.2 Database requirements still to validate

- Every tenant-owned row must have a clear organization/site ownership path.
- Every query must be tenant-scoped.
- Add indexes for common list/filter/order operations.
- Add uniqueness and foreign-key constraints through migrations, not just ORM assumptions.
- Confirm cascade deletes do not erase records that must be retained for audit, billing, or legal reasons.
- Define soft-delete behavior for organizations, websites, users, and connections.
- Define retention cleanup jobs and prove they respect legal/audit requirements.
- Test migrations from an empty database and from the previous released schema.
- Test rollback and forward-fix strategy for failed migrations.
- Test backup restoration into a clean environment.

---

# 6. Security and Autonomy Requirements

## 6.1 Permission layers

A URL alone grants only public read-only discovery.

Required sequence:
1. Register URL.
2. Verify domain ownership for recurring monitoring.
3. Connect a CMS/deployment provider for write access.
4. Request only the minimum scopes needed.
5. Store credentials encrypted.
6. Enable automation policy explicitly.
7. Gate each task by operation allowlist, risk tier, approval state, and current website status.

Domain verification does not automatically grant publishing permission.

## 6.2 Risk policy

| Risk tier | Examples | Required policy |
|---|---|---|
| Tier 1 | Narrow, reversible metadata correction with verified page target | May auto-execute only if customer explicitly enables it and connector operation is allowlisted |
| Tier 2 | Canonical/content/redirect/indexability changes | Human approval by default |
| Tier 3 | Destructive, broad, security-sensitive, or hard-to-reverse changes | Block by default or require explicit elevated approval and tested recovery |

Never automatically:
- Remove pages.
- Change broad URL structures.
- Add redirects without validated target mapping.
- Change robots/noindex/canonical directives without policy checks.
- Publish unreviewed large-scale content.
- Modify credentials, users, permissions, billing, or site security settings.

## 6.3 Mandatory write safety

Before a write:
- Confirm domain is verified.
- Confirm connector is connected and credential is valid.
- Confirm operation is allowlisted.
- Confirm website is active and not paused.
- Confirm task idempotency key.
- Confirm approval policy.
- Fetch and persist current state.
- Validate target and scope.
- Ensure the task is not stale.

After a write:
- Fetch remote state again.
- Validate exact intended change.
- Store before/after state.
- Store actor, connector, task, approval and timestamps.
- Mark validation passed/failed.
- Notify user.
- Offer rollback only if exact prior state can be restored.

## 6.4 SSRF and crawler security

The crawler fetches arbitrary customer-supplied URLs, so SSRF protection is critical.

Required protections:
- Permit only HTTP/HTTPS.
- Reject localhost, private, loopback, link-local, multicast, reserved, and metadata-service addresses.
- Resolve DNS and validate every resolved address.
- Revalidate DNS and IP after redirects.
- Prevent DNS rebinding.
- Block non-public IPv4 and IPv6 destinations.
- Enforce response size, redirect count, timeouts, and content-type allowlist.
- Never fetch file, FTP, gopher, or other unsupported schemes.
- Do not forward credentials/cookies to discovered URLs.
- Prevent cross-site credential leakage.
- Log safe error summaries without secrets or sensitive response bodies.
- Test IPv4, IPv6, encoded IPs, alternate numeric forms, redirects, DNS rebinding, and metadata endpoints.

## 6.5 Prompt injection and AI isolation

- Treat crawled page content, HTML, metadata, sitemaps, and third-party text as untrusted input.
- Never follow instructions found inside crawled pages.
- AI receives bounded evidence and task context, not raw credentials.
- AI cannot directly access database credentials, OAuth tokens, shell, or unrestricted network tools.
- AI output must conform to strict schemas.
- Validate URLs, HTML/content fields, lengths, and allowed operations deterministically.
- AI may explain, prioritize, summarize, and draft; deterministic code enforces policy and validates technical conditions.
- Keep prompt templates versioned and tested.
- Log prompt/version metadata safely without storing unnecessary personal or sensitive content.

---

# 7. Google Search Console and Analytics

## 7.1 Search Console

Search Console is the primary first-party search-performance integration.

Required:
- OAuth consent with minimum scopes.
- State parameter validation and CSRF protection.
- Token encryption at rest.
- Refresh-token lifecycle and disconnect handling.
- Site-property selection and ownership/access checks.
- Query/page/date ingestion with API limits and pagination.
- Backfill and incremental sync.
- Last-sync time and sync errors.
- Data freshness labels.
- Clear handling of missing or delayed data.
- No claim of real-time rank telemetry.

Search Console is delayed and aggregated. Average position is not the same as a guaranteed exact live rank for every search/location/device.

## 7.2 GA4

GA4 is optional. Do not block the MVP if the customer does not connect it.

Keep Search Console and GA4 permissions/connections distinct even if the same Google OAuth client is used.

## 7.3 Third-party SEO data

No mandatory Semrush/Ahrefs/Moz subscription is required for MVP. Any future provider adapter must document:
- API terms and licensing.
- Data retention and redistribution rights.
- Rate limits and quota.
- Cost per customer/site.
- Failure behavior.
- Whether the provider data is cached.
- Whether the feature remains usable without the provider.

---

# 8. AI, Agents, and Cost Governance

## 8.1 Responsibility split

**Deterministic services own:**
- HTTP status and redirects.
- Robots and sitemap behavior.
- Canonical comparisons.
- Metadata length and presence checks.
- Internal-link target status.
- Rule severity and confidence.
- Opportunity impact/effort/risk template values.
- Score calculation.
- Permission checks.
- Approval decisions.
- Connector operation allowlists.
- Post-change validation.

**AI may own:**
- Explain a finding in understandable language.
- Draft title/meta/content proposals.
- Summarize Search Console trends.
- Suggest candidate internal links.
- Generate a weekly/monthly report.
- Explain tradeoffs and confidence.

## 8.2 Agent inventory

Current agent enum values:
- Content Optimization.
- Post-change QA.
- SEO Strategy.
- Internal Linking.

Execution Planner is deterministic logic, not a separate LLM agent.

## 8.3 Cost controls

Current defaults:
- `gpt-4o-mini`
- 30-second timeout
- 1,200 max output tokens
- USD 1.00/day per website

Required additional controls:
- Global daily and monthly budgets.
- Per-organization budgets.
- Per-site budget reservation with transaction safety.
- Maximum input tokens/context size.
- Maximum concurrent AI calls.
- Retry ceilings.
- AI kill switch.
- Usage alerts at configurable thresholds.
- Cost dashboard with estimated internal cost and provider billing clearly distinguished.
- Fallback behavior when OpenAI is unavailable.
- No repeated AI calls when a deterministic result is sufficient.

---

# 9. Environment Configuration

Backend uses Pydantic Settings with `env_prefix="RANKPILOT_"`. The inspected configuration includes:

| Variable | Default / status | Purpose |
|---|---|---|
| `RANKPILOT_ENVIRONMENT` | `development` | Environment |
| `RANKPILOT_DATABASE_URL` | Local dev PostgreSQL URL | Database |
| `RANKPILOT_REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `RANKPILOT_CORS_ALLOWED_ORIGINS` | Localhost origins | CORS allowlist |
| `RANKPILOT_JWT_SECRET` | `change-me-in-production` | JWT signing; replace |
| `RANKPILOT_JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `RANKPILOT_ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Token expiry |
| `RANKPILOT_ALLOWED_URL_SCHEMES` | `http,https` | URL schemes |
| `RANKPILOT_OPENAI_API_KEY` | Optional | OpenAI credential |
| `RANKPILOT_OPENAI_MODEL` | `gpt-4o-mini` | AI model |
| `RANKPILOT_OPENAI_REQUEST_TIMEOUT_SECONDS` | `30.0` | Request timeout |
| `RANKPILOT_OPENAI_MAX_OUTPUT_TOKENS` | `1200` | Output ceiling |
| `RANKPILOT_AI_DAILY_BUDGET_USD_PER_SITE` | `1.0` | Per-site AI ceiling |
| `RANKPILOT_GOOGLE_CLIENT_ID` | Optional | Google OAuth |
| `RANKPILOT_GOOGLE_CLIENT_SECRET` | Optional | Google OAuth |
| `RANKPILOT_GOOGLE_OAUTH_REDIRECT_URI` | Local development callback | Search Console callback |
| `RANKPILOT_GOOGLE_GA4_OAUTH_REDIRECT_URI` | Local development callback | GA4 callback |
| `RANKPILOT_TOKEN_ENCRYPTION_KEY` | Optional in config; required for encrypted tokens | Fernet key |
| `RANKPILOT_SMTP_HOST` | Optional | SMTP host |
| `RANKPILOT_SMTP_PORT` | `587` | SMTP port |
| `RANKPILOT_SMTP_USERNAME` | Optional | SMTP user |
| `RANKPILOT_SMTP_PASSWORD` | Optional | SMTP password |
| `RANKPILOT_SMTP_FROM_EMAIL` | `no-reply@rankpilot.ai` | Sender |
| `RANKPILOT_SMTP_USE_TLS` | `true` | SMTP TLS |
| `RANKPILOT_PAGE_SNAPSHOT_RETENTION_DAYS` | `90` | Snapshot retention |
| `RANKPILOT_AUDIT_EVENT_RETENTION_DAYS` | `365` | Audit retention |
| `RANKPILOT_NOTIFICATION_RETENTION_DAYS` | `180` | Notification retention |

## 9.1 Production configuration rules

- Set `RANKPILOT_ENVIRONMENT=production`.
- Replace the JWT development secret.
- Use production PostgreSQL and Redis URLs.
- Bind PostgreSQL and Redis to private interfaces only.
- Set exact production CORS origins.
- Put OpenAI key only in backend/worker secret injection.
- Register exact Google OAuth callback URLs.
- Generate a stable Fernet key and protect it separately.
- Do not rotate the encryption key without a tested re-encryption migration.
- Keep SMTP credentials out of Git.
- Do not commit `.env` files or secret-bearing PM2 configuration.
- Ensure each PM2 process receives only the environment variables it needs.

## 9.2 Controls not verified in central config

The inspected `app/config.py` did not establish:
- Global API rate limits.
- Global crawl concurrency ceiling.
- Global AI spend ceiling.
- Universal per-host requests-per-second.
- Universal redirect-hop maximum.
- Universal response-body size ceiling.

These may exist elsewhere in the repository, but must be verified before being relied upon.

---

# 10. Existing VPS Deployment Requirements

## 10.1 Known VPS context

The founder's existing Database Mart VPS was previously observed with:
- 4 CPU cores.
- Approximately 8 GB RAM.
- Approximately 142 GB disk.
- After removing unused n8n data, approximately 19 GB used and 118 GB available.
- Existing PM2-managed products include other applications.

The previous disk figures are historical observations, not live server state. Recheck before deployment.

## 10.2 Shared-host deployment policy

- Do not buy a new VPS until the existing host is inspected and load-tested.
- Keep RankPilot isolated from other products.
- Start crawl worker concurrency at 1.
- Set conservative crawl budgets for founder pilot sites.
- Use process-level memory limits and restart policies.
- Monitor CPU, RAM, disk, inode usage, database size, Redis memory, queue depth, and worker failures.
- Do not allow RankPilot crawling to starve existing applications.
- Run PostgreSQL/Redis only once; do not create duplicate services if a suitable managed/local service already exists.
- Backups must be copied to an external encrypted location, not only stored on the same VPS.

## 10.3 Pre-deployment inspection checklist

- [ ] Current CPU/RAM/disk/inodes.
- [ ] Current PM2 process list and memory.
- [ ] Nginx configuration and active virtual hosts.
- [ ] Existing PostgreSQL version, databases, connections, disk usage.
- [ ] Existing Redis version, memory, persistence and port binding.
- [ ] Open ports and firewall rules.
- [ ] TLS certificate and renewal.
- [ ] Available disk space for logs, snapshots and backups.
- [ ] External backup destination and credentials.
- [ ] Restore test completed.
- [ ] Application secrets and ownership/permissions checked.
- [ ] Process restart behavior tested.
- [ ] Resource limits configured.

## 10.4 Suggested process separation

Where PM2 is used:
- `rankpilot-web`
- `rankpilot-api`
- `rankpilot-worker`
- `rankpilot-scheduler`

Database and Redis should be managed as dedicated services or managed infrastructure, not duplicated per PM2 app.

---

# 11. QA Strategy and Release Gates

## 11.1 Test layers

1. Unit tests: URL normalization, SSRF validation, extraction, every SEO rule, scoring, budget enforcement, approval policy.
2. Integration tests: PostgreSQL, Redis, Celery, OAuth, OpenAI mocked responses, connector APIs.
3. API tests: authentication, roles, tenant isolation, validation, error handling, pagination.
4. Security tests: SSRF, prompt injection, secrets exposure, CSRF, OAuth state, IDOR, rate limits.
5. Connector tests: scopes, operation allowlist, idempotency, before/after, validation, rollback.
6. Crawl tests: robots, sitemaps, redirects, timeouts, malformed HTML, large files, cycles, partial failure.
7. End-to-end tests: registration → verification → crawl → findings → opportunity → approval → write → validation.
8. Performance tests: concurrent users, crawl load, queue backlog, memory growth, database query performance.
9. Recovery tests: worker crash, Redis restart, database restart, backup restore, connector outage.

## 11.2 Golden SEO dataset

Do not invent a universal accuracy percentage. Build a labeled dataset from founder-owned sites.

For every implemented rule, record:
- Pages reviewed.
- True positives.
- False positives.
- False negatives.
- Precision.
- Recall.
- Reviewer.
- Review date.
- Code/rule version.

Test every rule with positive and negative fixtures, including exact threshold boundaries.

**Provisional deterministic-rule release gate:** 100% pass on explicitly authored positive/negative unit fixtures for every implemented rule. This is a test-suite requirement, not a claim of 100% real-world precision.

## 11.3 Write automation release gate

No expansion of autonomous publishing until:
- [ ] No critical SSRF defect remains.
- [ ] No cross-tenant access defect remains.
- [ ] No unauthorized-write test fails.
- [ ] Every write has before/after evidence.
- [ ] Every write has deterministic post-change validation.
- [ ] Rollback is tested for each operation advertised as reversible.
- [ ] Approval policy is enforced server-side.
- [ ] Idempotency and duplicate-task protection pass.
- [ ] Pilot false-positive rates have been measured and accepted.
- [ ] Kill switch and pause controls have been tested.

---

# 12. Required Work Register

The following register is the consolidated work that must be completed or explicitly accepted as out of scope before the MVP can be called ready.

| ID | Priority | Requirement / action | Acceptance evidence |
|---|---|---|---|
| RP13-001 | P0 | Audit all API routes for tenant isolation | Automated cross-tenant tests pass |
| RP13-002 | P0 | Remove production use of default JWT secret | Startup fails closed if default used in production |
| RP13-003 | P0 | Add verification-token expiry and replay protection | Expired/reused token tests pass |
| RP13-004 | P0 | Add verification rate limiting | Repeated attempts are throttled |
| RP13-005 | P0 | Add crawler response byte limits | Oversized response safely rejected |
| RP13-006 | P0 | Add redirect-hop ceiling and validate every redirect target | Redirect/SSRF tests pass |
| RP13-007 | P0 | Add DNS rebinding and IPv6 SSRF tests | Private/metadata targets always blocked |
| RP13-008 | P0 | Add per-host crawl rate controls | Load tests show configured limits respected |
| RP13-009 | P0 | Add sitemap recursion/size/URL limits | Malicious/huge sitemap tests pass |
| RP13-010 | P0 | Add crawl cancellation and website pause behavior | Cancelled/paused crawl stops safely |
| RP13-011 | P0 | Prevent duplicate active crawl jobs | Concurrent request test creates one active job |
| RP13-012 | P0 | Add global AI budget and kill switch | Global ceiling and disabled state tested |
| RP13-013 | P0 | Make per-site AI budget reservation concurrency-safe | Concurrent calls cannot overspend configured cap |
| RP13-014 | P0 | Add prompt/input size ceilings | Oversized context is rejected/truncated safely |
| RP13-015 | P0 | Verify OpenAI key never reaches frontend/logs | Secret scan and browser inspection pass |
| RP13-016 | P0 | Complete WordPress operation allowlist documentation | Each operation has exact scope and tests |
| RP13-017 | P0 | Test before/after evidence and post-write validation | End-to-end write test passes |
| RP13-018 | P0 | Prove rollback for each advertised reversible operation | Restore test passes |
| RP13-019 | P0 | Confirm migrations match SQLAlchemy models | Clean install and upgrade tests pass |
| RP13-020 | P0 | Confirm retention jobs and audit preservation | Retention tests pass |
| RP13-021 | P0 | External backup and restore runbook | Restore to clean environment demonstrated |
| RP13-022 | P0 | Shared VPS resource/load test | CPU/RAM/disk/queue thresholds documented |
| RP13-023 | P0 | Golden SEO fixtures for every implemented rule | Positive/negative and boundary tests pass |
| RP13-024 | P0 | Founder pilot on owned custom sites | Pilot report with reviewed findings |
| RP13-025 | P1 | Add Playwright rendering fallback if pilot evidence requires it | JS-rendered test-site comparison |
| RP13-026 | P1 | Implement DNS TXT/meta verification if product requires | Method-specific tests pass |
| RP13-027 | P1 | Add agency-level reporting | Multi-site report acceptance test |
| RP13-028 | P1 | Complete billing/subscription enforcement | Plan limits and payment lifecycle tests |
| RP13-029 | P1 | Add API/global rate limiting | Abuse/load tests pass |
| RP13-030 | P1 | Add global queue and per-tenant concurrency controls | Fair scheduling tests pass |

Do not mark an item complete because a model, route, enum, or placeholder file exists. Require evidence.

---

# 13. Founder Pilot Plan

## Phase A — Safe read-only baseline

1. Choose one founder-owned custom website.
2. Confirm permission and ownership.
3. Register and verify it.
4. Run a small crawl budget first.
5. Inspect page inventory and crawl coverage.
6. Review each finding against the actual page.
7. Record false positives and missed issues.
8. Connect Search Console if available.
9. Compare the platform's evidence with Search Console's historical data.
10. Do not publish changes in this phase.

## Phase B — Recommendation quality

1. Select a small number of high-confidence opportunities.
2. Ask AI for structured explanations/proposals.
3. Review every proposal manually.
4. Reject unsupported claims and vague recommendations.
5. Measure token use and estimated cost.
6. Tune prompts and deterministic rule evidence.
7. Repeat across more founder-owned pages/sites.

## Phase C — Controlled write validation

1. Use a staging WordPress site or a safe test page first.
2. Connect with minimum permissions.
3. Enable only a narrow Tier 1 operation.
4. Capture before state.
5. Execute one bounded change.
6. Fetch and validate after state.
7. Confirm audit record.
8. Test rollback.
9. Test failure handling and duplicate-task prevention.
10. Only then consider a limited production pilot.

## Phase D — Ongoing pilot

Track weekly:
- Crawl coverage and failures.
- Findings by rule and severity.
- False-positive/false-negative review.
- Opportunities accepted/rejected.
- Changes executed and validation results.
- Rollback attempts and success.
- Search Console clicks, impressions, CTR and average position where available.
- AI calls, token usage, estimated cost and provider billing.
- VPS resource usage and queue depth.
- Founder/user feedback.

Do not claim SEO impact from a short observation window or attribute every ranking change to RankPilot.

---

# 14. Product Metrics

## Reliability
- Crawl success rate.
- Crawl coverage vs discovered sitemap/page inventory.
- Queue wait time.
- Worker failure/retry rate.
- API availability and latency.
- Notification delivery rate.

## SEO quality
- Rule-level precision and recall.
- Findings reviewed.
- Opportunities accepted/rejected.
- Duplicate or stale finding rate.
- Change validation pass rate.

## Automation safety
- Unauthorized writes (target: zero).
- Changes with complete before/after evidence (target: 100%).
- Changes with post-change validation (target: 100%).
- Rollback success for supported reversible operations.
- Human approval compliance.

## Cost and business
- AI cost per site.
- Infrastructure cost per site.
- Crawl cost per site.
- Gross margin by plan.
- Trial-to-paid conversion after billing exists.
- Retention and active monitored sites.

---

# 15. Documentation and Change Control

Any change to API paths/schemas, database models/enums/constraints, SEO thresholds, score formula, risk tiers, connector scopes, retention, AI model/budgets, or deployment topology must include:
1. Code change.
2. Automated tests.
3. Migration where required.
4. Updated documentation in the same pull request.
5. Before/after behavior note.
6. Security and tenant-isolation review where applicable.
7. Rollback or forward-fix plan.

## 15.1 Source-of-truth hierarchy

1. Security and product-safety requirements in this document.
2. Executable code, migrations, and tests for currently implemented behavior.
3. This document for consolidated product intent, implementation facts, gaps, and acceptance requirements.
4. Other older specification files for detail, provided they do not conflict with this version.

When code and documentation disagree:
- Do not silently assume either side is correct.
- Create a reconciliation issue.
- Decide whether code or specification should change.
- Update both in the same reviewed change.
- Record whether the item is implemented, partial, planned, blocked, or not applicable.

---

# 16. Final MVP Readiness Checklist

RankPilot AI may be called **Founder Pilot Ready** only when all P0 gates below have evidence:

- [ ] Clean installation and database migrations pass.
- [ ] Authentication and tenant isolation tests pass.
- [ ] Production secrets are configured securely.
- [ ] Domain verification is secure and rate-limited.
- [ ] SSRF and crawler safety tests pass.
- [ ] Crawl budgets, rate limits, response limits, and cancellation work.
- [ ] Every implemented SEO rule has positive/negative/boundary tests.
- [ ] Findings and opportunities have correct lifecycle behavior.
- [ ] Search Console connection works or is clearly marked optional/unavailable.
- [ ] AI output schema validation works.
- [ ] Per-site and global AI budgets/kill switch work.
- [ ] AI key is never exposed to the browser or logs.
- [ ] WordPress write operations are allowlisted and permission-gated.
- [ ] Approval policy is enforced server-side.
- [ ] Before/after records and post-change validation work.
- [ ] Rollback claims are proven operation by operation.
- [ ] Notifications and audit history work.
- [ ] Retention and deletion policies are tested.
- [ ] External backup and restore are demonstrated.
- [ ] Shared VPS load test is completed without harming existing products.
- [ ] Founder-owned website pilot findings are manually reviewed.
- [ ] Known limitations are visible to the user.

**Commercial Launch Ready** is a separate milestone. It additionally requires billing, plan limits, customer support procedures, privacy/terms, incident response, production monitoring, and a validated capacity/cost model.

---

# 17. Explicit Limitations and Unknowns

The repository inspection summarized in this document does not establish:
- That every test suite passes.
- That all migrations match all model definitions.
- That every connector operation is complete or safe for production.
- That all external OAuth flows have been tested against live provider accounts.
- That a global AI spend cap exists.
- That global API rate limits exist.
- That a global crawl concurrency cap exists.
- That maximum response size and redirect limits are enforced everywhere.
- That backups have been restored successfully.
- That the shared VPS has been load-tested with RankPilot.
- That billing is complete.
- That rankings or traffic have improved.

These are explicit verification tasks, not assumptions.

---

# 18. Final Decision

**Recommended status: Continue as a controlled founder pilot, not a commercial production launch.**

First priority is to finish P0 safety, tenant isolation, crawler limits, AI cost governance, connector write safety, test evidence, backup/restore, and shared-VPS load validation.

Use founder-owned custom websites to validate read-only crawling and SEO finding quality first. Add controlled writes only after the safety gates in this document pass.

No new paid SEO provider is required to begin this validation. The user's OpenAI API key can power AI explanations and proposals, while deterministic code remains responsible for technical SEO checks, scoring, permissions, and execution policy.

---

# 19. P0 Completion Status (added after this document, not part of the original)

Per Section 15's change-control policy: record whether each item is implemented,
partial, planned, blocked, or not applicable, rather than silently assuming. This
section was added in a follow-up session that worked the P0 register in Section 12
end to end. The original Section 12 table above is left exactly as given; this is a
status overlay on it, not an edit to it.

| ID | Status | Evidence |
|---|---|---|
| RP13-001 | **Done** | Full audit of every `db.query`/`db.get` call across all 10 endpoint files; no cross-tenant defect found. Added the few missing regression tests (crawls, usage, audit-events, verification). |
| RP13-002 | **Done** | `Settings` fails closed (`ValueError` at process startup) if `RANKPILOT_ENVIRONMENT=production` and the JWT secret is still the default. |
| RP13-003 | **Done** | `website_verifications.expires_at` now enforced (`RANKPILOT_VERIFICATION_TOKEN_EXPIRE_MINUTES`, default 24h). |
| RP13-004 | **Done** | Confirm attempts capped per verification row (`RANKPILOT_VERIFICATION_MAX_ATTEMPTS`, default 10), then locked out with a 429. |
| RP13-005 | **Done** (pre-existing, now directly tested) | Response-size cap (5 MB) was already in `fetch.py`; added direct unit tests against the real implementation. |
| RP13-006 | **Done** (pre-existing, bug fixed) | Redirect-hop ceiling existed; found and fixed a real bug in the same code path -- `httpx.URL.human_repr()` doesn't exist in the installed httpx version, so every real redirect previously raised. |
| RP13-007 | **Done** | Found and fixed a real DNS-rebinding gap: the crawler and verification fetchers re-resolved DNS at connect time after `validate_public_url` had already validated a different resolution. Fixed by pinning the connection to the validated IP (Host header + TLS SNI kept on the real hostname), confirmed correct against httpcore's own source. IPv6 was already covered by the existing resolver logic. |
| RP13-008 | **Done** | Crawls now wait a minimum 0.5s between same-host fetches, or longer if robots.txt declares a larger `Crawl-delay`. |
| RP13-009 | **Done** (pre-existing limits, new protection added) | File/URL-count limits already existed; added a DOCTYPE rejection in sitemap XML parsing to close an entity-expansion ("billion laughs") path the size cap didn't cover. |
| RP13-010 | **Done** | New `CrawlStatus.cancelled`, a cancel endpoint, and pause-triggered cancellation checked every loop iteration via `db.refresh`. |
| RP13-011 | **Done** | `trigger_crawl` rejects a second concurrent crawl for the same website with 409. |
| RP13-012 | **Done** | Global daily budget (`RANKPILOT_AI_GLOBAL_DAILY_BUDGET_USD`) and kill switch (`RANKPILOT_AI_KILL_SWITCH_ENABLED`). |
| RP13-013 | **Done** | Budget check now acquires a transaction-scoped Postgres advisory lock per website; verified with real concurrent threads against a real Postgres connection, not mocks. |
| RP13-014 | **Done** | `RANKPILOT_AI_MAX_PROMPT_CHARACTERS` (default 20000) rejects an oversized prompt before any budget check or API call. |
| RP13-015 | **Done** | Full audit: no frontend reference, no logging near settings, no custom exception handler, `debug=False` confirmed. Added regression tests (allowed-file-list check, generic-500 check). |
| RP13-016 | **Done** | New `docs/CONNECTOR_OPERATIONS_REFERENCE.md`. Found and fixed a real scope-accuracy gap: Shopify's recorded scopes didn't cover product metafields. |
| RP13-017 | **Done** | Every connector now has a full `execute_task` happy-path test with before/after evidence. |
| RP13-018 | **Done** | Found a real gap: a GitHub test claimed to prove rollback but never triggered it. Fixed, and added the two other missing rollback tests (Shopify, and confirmed Webflow/WordPress already had theirs). |
| RP13-019 | **Done** | `alembic check` reports no drift; `scripts/check_clean_install.sh` runs the full migration chain against a brand-new database and the full test suite against the result -- run and verified in this session. |
| RP13-020 | **Done** | Found a real gap: `AuditEvent`/`UsageRecord` cascade-deleted with their organization/website. Changed to `SET NULL`; verified at the database level that the rows survive a real delete. |
| RP13-021 | **Done** | Ran the existing runbook's backup/restore procedure for real: seeded data, `pg_dump`, `gpg` encrypt, delete plaintext, decrypt, `pg_restore` into a fresh database, verified exact row counts and a live API against it. Recorded in `ops/RUNBOOKS.md`'s verification log. Not run against a real production VPS. |
| RP13-022 | **Blocked** | Requires the real shared VPS; cannot be performed from this sandbox. |
| RP13-023 | **Done** | 45 new direct unit tests cover all 18 rule codes with positive/negative/boundary fixtures. |
| RP13-024 | **Needs the user** | Requires picking one of the user's actual websites and walking through Phase A of Section 13. |

All P0 items are closed except the two that structurally cannot be: RP13-022 needs
real infrastructure, and RP13-024 needs the account owner's own site and judgment.
