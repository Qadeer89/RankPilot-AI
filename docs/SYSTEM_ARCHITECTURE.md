# RankPilot AI --- System Architecture

## 1. Architecture principles

-   Start as a modular monolith with independently managed background
    workers.
-   Prefer deterministic SEO analysis; use AI for interpretation,
    prioritization and draft generation.
-   Keep provider integrations optional and adapter-based.
-   Separate read-only crawling from authorized write execution.
-   Design for tenant isolation, cost controls and safe retries.
-   Reuse the existing VPS for a constrained founder pilot, subject to
    capacity checks.

## 2. Proposed stack

  -----------------------------------------------------------------------
  Layer                               Technology
  ----------------------------------- -----------------------------------
  Frontend                            Next.js + TypeScript

  Backend API                         FastAPI + Python

  Database                            PostgreSQL

  Queue/cache                         Redis

  Background workers                  Celery workers + scheduler

  Crawling                            HTTP client/parser first;
                                      Playwright only for JS-rendered
                                      pages

  AI                                  Existing OpenAI API account/key,
                                      server-side only

  Reverse proxy                       Existing Nginx, subject to
                                      configuration

  Process management                  PM2 for Node and Python process
                                      supervision, or systemd where
                                      operationally preferable

  Deployment                          Existing Ubuntu VPS; no mandatory
                                      Docker dependency

  Observability                       Structured logs, health endpoints,
                                      resource monitoring
  -----------------------------------------------------------------------

The stack is a proposal. Confirm installed versions, existing database
services, ports and Nginx configuration before deployment.

## 3. Logical components

1.  Web application: onboarding, dashboard, approvals and reports.
2.  API service: authentication, tenancy, website configuration and API
    contracts.
3.  Crawl coordinator: crawl scheduling, robots/sitemap handling and
    crawl budgets.
4.  Crawler workers: fetch pages, render selected pages when needed,
    extract page signals.
5.  SEO rule engine: deterministic checks and evidence.
6.  Opportunity engine: combine findings, Search Console metrics and
    customer context.
7.  AI service adapter: OpenAI request routing, structured outputs,
    token limits and retries.
8.  Agent orchestrator: schedules and coordinates bounded tasks.
9.  Execution service: CMS connector operations, approvals, idempotency
    and rollback.
10. Validation service: recrawl and compare post-change state.
11. Integrations: Google Search Console, optional GA4, WordPress and
    future provider adapters.
12. Metering/notifications: usage records, cost attribution and alerts.

## 4. Main workflow

URL submitted → URL/domain verification → robots/sitemap discovery →
bounded crawl → page extraction → deterministic rules → optional Search
Console enrichment → opportunity scoring → AI explanation/proposal →
policy decision → approval or permitted execution → post-change
crawl/validation → dashboard/report.

Daily scheduler should not blindly repeat full crawls. Use changed URLs,
priority pages, sitemap deltas, freshness windows and plan-based crawl
budgets.

## 5. Background job types

-   `site_initial_discovery`
-   `site_crawl`
-   `page_render`
-   `technical_audit`
-   `search_console_sync`
-   `opportunity_refresh`
-   `ai_proposal`
-   `change_execution`
-   `post_change_validation`
-   `weekly_report`
-   `retention_cleanup`

Every job needs tenant/site scope, idempotency key, retry policy,
timeout, resource limits and traceable status.

## 6. Existing VPS deployment baseline

Observed on 2026-11-02: - 4 vCPU, 8 GB RAM, approximately 142 GB root
disk. - Approximately 118 GB free after removal of `/opt/n8n-data`. -
Other PM2-managed products are running on the same host. - n8n was
removed; RankPilot must not depend on it. - Existing host uses PM2 and
Nginx patterns.

This shared VPS is a pilot environment, not a guaranteed production
capacity. Before deploying: - Check current CPU/RAM/disk and inode
usage. - Inventory active ports and Nginx sites. - Identify whether
PostgreSQL/Redis already exist and their load. - Reserve memory/CPU for
existing applications. - Set worker concurrency to 1 initially; increase
only after load testing. - Keep Playwright browser jobs isolated and
bounded. - Configure external backups and restore tests. - Avoid
installing Docker unless a specific operational need justifies it.

## 7. Initial process layout

Suggested PM2/systemd-managed processes: - `rankpilot-web` ---
Next.js. - `rankpilot-api` --- FastAPI via a production ASGI server. -
`rankpilot-worker` --- Celery worker, initially low concurrency. -
`rankpilot-scheduler` --- Celery Beat or one scheduler process only.

Redis and PostgreSQL should run as managed system services or approved
existing managed services. Do not run duplicate databases if suitable
shared services exist.

## 8. Scaling strategy

1.  Founder pilot: shared VPS, one worker, limited sites/pages.
2.  Early beta: separate crawler worker process or small worker VPS if
    CPU/RAM contention appears.
3.  Growth: isolate API/database/worker tiers, add queue concurrency and
    object storage.
4.  Scale only from observed queue lag, crawl duration, memory pressure,
    database I/O and per-site cost.

## 9. Architecture decisions

-   No mandatory Semrush/Ahrefs/Moz dependency.
-   Third-party SEO data providers use a common adapter contract and
    remain disabled until justified.
-   OpenAI API key is provided by the founder and stored in server
    environment/secret storage; it is not committed or shared.
-   Public URL access does not imply permission to publish website
    changes.
-   Search Console is first-party performance context, not real-time
    rank tracking.
-   A daily schedule means daily checks and decisions, not forced daily
    edits.
