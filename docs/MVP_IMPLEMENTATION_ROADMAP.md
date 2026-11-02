# RankPilot AI --- MVP Implementation Roadmap

## 1. Delivery strategy

Build a useful end-to-end product in increments. Use founder-owned
websites as the first pilot cohort. Keep external SEO data providers out
of the critical path. Reuse the existing VPS initially, but do not
jeopardize other hosted products.

## 2. Phase plan

### Phase 0 --- Environment and cost readiness

-   Inspect VPS CPU/RAM/disk, ports, Nginx, PM2 and existing database
    services.
-   Confirm separate application user and directory.
-   Choose domain/subdomain and configure DNS/TLS.
-   Establish external encrypted backup destination.
-   Configure OpenAI API key server-side and set spending alerts/limits.
-   Create repository, environments and deployment workflow.

**Exit:** safe deployment slot and secrets/backup plan confirmed.

### Phase 1 --- Platform foundation

-   Next.js frontend and FastAPI backend.
-   Authentication, organizations and tenant isolation.
-   PostgreSQL migrations and Redis queue.
-   Website registration, URL validation and domain verification.
-   Basic dashboard and health checks.

**Exit:** user can add and manage a verified website.

### Phase 2 --- Crawl and deterministic SEO baseline

-   Robots/sitemap discovery.
-   Bounded HTTP crawler and selective Playwright fallback.
-   Page inventory and snapshots.
-   Technical/on-page rule engine.
-   Findings dashboard and evidence.

**Exit:** founder can run repeatable baseline audits on owned websites.

### Phase 3 --- Search performance and AI opportunities

-   Search Console OAuth and property mapping.
-   Search metrics ingestion with freshness labels.
-   Opportunity scoring.
-   OpenAI structured analysis and content proposals.
-   Cost metering and per-site AI budgets.

**Exit:** evidence-backed, reviewable SEO action plan.

### Phase 4 --- Safe execution

-   WordPress connector for a pilot site if applicable.
-   Approval policy and risk tiers.
-   Bounded metadata/content operations.
-   Before/after capture and deterministic post-change validation.
-   Pause, audit and rollback where supported.

**Exit:** safe end-to-end change on an owned test site.

### Phase 5 --- Daily operations and reporting

-   Daily scheduler and changed-page recrawl.
-   Opportunity refresh and policy-eligible actions.
-   Email activity summaries.
-   Weekly report and Search Console trend views.
-   Retention, quota and resource controls.

**Exit:** stable daily loop on founder-owned pilot websites.

### Phase 6 --- Private beta readiness

-   Security and load testing.
-   Multi-site workspace checks.
-   Backup/restore validation.
-   Cost per site and gross-margin model.
-   Onboard a small number of external design partners only after pilot
    evidence.

## 3. Deferred work

-   Semrush/Ahrefs/Moz APIs.
-   Full rank-tracking database and global backlink index.
-   Broad CMS write support.
-   Full agency white-label suite.
-   Shopify/Webflow unless pilot demand requires them.
-   Advanced competitor intelligence and automated link building.

## 4. Suggested initial team

Founder-led, AI-assisted implementation is assumed for planning. Add
specialist help only where required for security, integrations, design
or delivery. Do not assume developer labour is free in financial models;
track hours separately from cash spend.

## 5. Milestone gates

Each phase requires demo, QA evidence, security review where applicable,
operational cost measurement and explicit go/no-go. Do not move to
autonomous writes before read-only findings are sufficiently accurate on
the founder's sites.
